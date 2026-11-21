/* Derived geometry v3: one local metric plane, static parallel offsets.
 * Cache lives only in this renderer; native paths and Motion_Plan stay intact. */
// Shared presentation catalog: labels, rigid bodies, spacing and diagnostics all
// resolve the same record. Family defaults are explicit visual assumptions,
// never PCU or measured dimensions. Registered configuration remains separate
// and can supply a body without being presented as a physical measurement.
class SimZ1VehicleCatalog {
  static version='simz1-vehicle-presentation-v1';
  static assumptions=Object.freeze(Object.fromEntries(Object.entries({
    car:[4.5,1.8],motorcycle:[2.1,.8],truck:[10,2.5],bus:[12,2.5],
    articulated_bus:[18,2.5],unknown:[4.5,1.8]
  }).map(([family,[length_m,width_m]])=>[family,Object.freeze({length_m,width_m,
    source:'assumed:'+SimZ1VehicleCatalog.version+':'+family,assumed:true})])));
  static normalize(value) {
    return typeof value==='string' ? value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[ _-]/g,'').trim() : '';
  }
  static aliases=Object.freeze(Object.fromEntries(Object.entries({normal:['car',null],car:['car',null],carro:['car',null],
      liebre:['car','Liebre'],carroliebre:['car','Liebre'],tortuga:['car','Tortuga'],carrotortuga:['car','Tortuga'],
      motociclista:['motorcycle',null],motocicleta:['motorcycle',null],moto:['motorcycle',null],motorcycle:['motorcycle',null],
      motocicletalenta:['motorcycle','Tortuga'],mototortuga:['motorcycle','Tortuga'],motociclistalenta:['motorcycle','Tortuga'],
      motocicletanormal:['motorcycle','Normal'],motocicletarapida:['motorcycle','Liebre'],motoliebre:['motorcycle','Liebre'],
      transportepesado:['truck',null],truck:['truck',null],freighttruck:['truck',null],
      transitbus:['bus',null],bus:['bus',null],transmetrorigidproxy:['bus',null],tubusrigidproxy:['bus',null],
      transportepublico:['passenger',null]
  }).map(([name,value])=>[name,Object.freeze(value)])));
  static type(value) {
    const key=this.normalize(value);
    const found=Object.hasOwn(this.aliases,key) ? this.aliases[key] : null;
    return found ? {family:found[0],profile:found[1]} : null;
  }
  static profile(value) {
    const key=this.normalize(value);
    return key==='normal' ? 'Normal' : key==='liebre' ? 'Liebre' : key==='tortuga' ? 'Tortuga' : null;
  }
  static resolve(record={}) {
    const explicit=value=>typeof value==='string' && value.trim() ? value : null;
    const vehicleType=explicit(record.Vehicle_Type),agentType=explicit(record.Agent_Type);
    // A passenger category alone is not a bus, and IDs/PCU/speed never infer a family.
    const type=vehicleType ?? agentType;
    const alias=type ? this.type(type) : null;
    const known=vehicleType && alias?.family==='passenger' ? {family:'bus',profile:null} : alias;
    const historical=!type && this.profile(record.Profile);
    const family=record.Vehicle_Family==='bus' && record.Trip?.Transit?.schema==='simz1-transit-replay-v1' ?
      'bus' : known?.family ?? (historical ? 'car' : 'unknown');
    const explicitProfile=this.profile(record.Driving_Profile),recordedProfile=this.profile(record.Profile);
    const profile=explicitProfile ?? known?.profile ?? recordedProfile ??
      (family==='car' || family==='motorcycle' ? 'Normal' : null);
    const profileSource=explicitProfile ? 'Driving_Profile' : known?.profile ? 'type_alias' :
      recordedProfile ? 'Profile' : profile ? 'presentation_default' : 'not_recorded';
    const publicLabel=({transmetrorigidproxy:'Transmetro',tubusrigidproxy:'TuBus'})[this.normalize(vehicleType)];
    const label=family==='car' ? ({Normal:'Carro',Liebre:'Carro liebre',Tortuga:'Carro Tortuga'})[profile] :
      family==='motorcycle' ? ({Normal:'Moto',Liebre:'Moto Liebre',Tortuga:'Moto tortuga'})[profile] :
      family==='truck' ? 'Camión' : family==='bus' ? publicLabel ?? 'Transporte público' :
      family==='passenger' ? 'Transporte público' : type ?? 'No registrado';
    const dimensionDiagnostics=[];
    const recordedDimensions=(value,field,physical=false)=>{
      if(value==null)return null;
      const invalid=!value || typeof value!=='object' || Array.isArray(value) ||
        ![value.length_m,value.width_m].every(n=>Number.isFinite(n) && n>0) ? 'invalid_positive_metric_dimensions' :
        !explicit(value.source) ? 'missing_dimension_source' : null;
      if(invalid){dimensionDiagnostics.push({field,reason:invalid});return null;}
      return Object.freeze({length_m:value.length_m,width_m:value.width_m,source:value.source,
        assumed:typeof value.assumed==='boolean' ? value.assumed : physical ? null : false,
        provenance:value.provenance ?? null,...(value.articulated===true ? {articulated:true} : {}),
        ...(physical ? {nature:value.nature ?? 'configured',
          measurement_status:value.measurement_status ?? 'not_established_by_vehicle_type'} : {})});
    };
    // The explicit presentation override wins. A recorded VehicleType is the
    // next source, before family assumptions; PCU never supplies metres.
    // Invalid optional records are diagnosed locally, not allowed to abort the
    // entire frame or remove the vehicle whose body can use another source.
    const visualDimensions=recordedDimensions(record.Vehicle_Dimensions,'Vehicle_Dimensions');
    const physicalDimensions=recordedDimensions(record.Vehicle_Physical_Dimensions,'Vehicle_Physical_Dimensions',true);
    const selectedDimensions=visualDimensions ?? physicalDimensions;
    const articulated=record.Vehicle_Articulated===true || selectedDimensions?.articulated===true;
    const recordedVehicle=typeof record.vehicle==='string' && record.vehicle.length>0 || Number.isFinite(record.vehicle);
    // Retain a recorded, untyped moving vehicle as unknown geometry; the
    // passenger label alone must neither create a bus nor hide that identity.
    let dimensions=family==='passenger' ? (recordedVehicle ? this.assumptions.unknown : null) :
      this.assumptions[articulated && family==='bus' ? 'articulated_bus' : family];
    const dimensionsOrigin=!dimensions ? 'not_applicable_without_recorded_vehicle' : visualDimensions ? 'recorded_visual' :
      physicalDimensions ? 'recorded_physical' : 'family_assumption';
    if(dimensions && selectedDimensions)dimensions=selectedDimensions;
    return {catalog_version:this.version,family,driving_profile:profile,driving_profile_source:profileSource,
      recorded_driving_profile:record.Driving_Profile ?? record.Profile ?? null,label,
      recorded_vehicle_type:vehicleType,recorded_agent_type:agentType,dimensions,dimensions_origin:dimensionsOrigin,
      dimension_diagnostics:dimensionDiagnostics,
      operator:record.Trip?.Transit?.operator ?? record.Transit_Operator ?? record.Operator ?? record.operator ?? null,
      service:record.Trip?.Transit?.service_id ?? record.Transit_Service ?? record.Service ?? record.service ?? null,
      body_model:articulated && family==='bus' ? 'rigid_total_envelope_articulation_unknown' : 'rigid',
      limitation:articulated && family==='bus' ? 'Sin poses de articulación: envolvente total rígida, no trayectoria de módulos.' :
        family==='passenger' ? 'Categoría de pasajero sin vehículo de servicio registrado.' : null,
      physical:{pcu:record.Vehicle_PCU ?? null,maximum_speed_mps:record.Motion_Provenance?.vehicle_limit_mps ?? null,
        dimensions:physicalDimensions,dimensions_status:record.Vehicle_Physical_Dimensions==null ? 'not_recorded' :
          physicalDimensions ? 'recorded' : 'invalid'}};
  }
}

class SimZ1VisualLanes {
  constructor(options) {
    this.options=options || {};this.paths=new WeakMap();this.links=new Map();
    this.pathCompatibility=new WeakMap();this.descriptions=new Map();this.storageDescriptions=new Map();
    this.cacheVersion=3;this.roadCache=[];this.connectorCache=[];this.geometryIssues=[];this.ambiguousConnectors=0;this.reversingConnectors=0;
    this.insetConnectors=0;this.recordedLaneJoins=new Map();this.recordedLaneCurves=new Map();
    if(this.options.schema_version!==1 || !this.options.links || typeof this.options.links!=='object')return;
    let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
    for(const link of Object.values(this.options.links))for(const p of Array.isArray(link?.path) ? link.path : []) {
      if(!this.validPoint(p))continue;
      minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
    }
    if(Number.isFinite(minX))this.setProjection([(minX+maxX)/2,(minY+maxY)/2]);
    for(const [id,link] of Object.entries(this.options.links)) {
      if(!link || typeof link!=='object')continue;
      const lanes=link.num_lanes,opposing=link.opposing_lanes ?? 0;
      const eligible=link.offset_eligible!==false && Number.isSafeInteger(lanes) && lanes>=1 && lanes<=12 &&
        Number.isSafeInteger(opposing) && opposing>=0 && opposing<=12 && (!opposing || typeof link.reverse_link==='string');
      const requested=link.lane_width_m ?? this.options.lane_width_m;
      const width=Number.isFinite(requested) && requested>0 ? Math.min(3.5,requested) : 3;
      const base=this.geometry(link.path);
      this.links.set(id,{id,data:link,lanes,opposing,width,eligible,assignmentKey:id,
        geometry:base ? {...base,offsets:new Map(),joins:{}} : null});
    }
    this.prepareGeometry();
    this.nodeLinks=new Map();this.stopMargins=new Map();
    for(const link of this.links.values())for(const node of [link.data.from_node,link.data.to_node]) {
      if(node==null)continue;
      if(!this.nodeLinks.has(node))this.nodeLinks.set(node,[]);
      this.nodeLinks.get(node).push(link);
    }
    this.labelCandidates=this.buildLabelCandidates();
    this.occupancyCorridors=new Map();this.occupancyLinks=new Map();
    const occupancy=this.options.occupancy_corridors;
    if(occupancy?.schema==='corridor-length-v1')for(const [id,data] of Object.entries(occupancy.corridors || {})) {
      const members=(data.link_ids || []).map(key=>this.links.get(key));
      if(!members.length || members.some(link=>!link?.eligible || !link.geometry) ||
         members.some((link,i)=>i && !this.connects(members[i-1],link)))continue;
      let offset=0;const parts=members.map(link=>{const part={link,offset,length:link.geometry.length};offset+=part.length;return part;});
      const corridor={id,data,parts,length:offset};this.occupancyCorridors.set(id,corridor);
      for(const part of parts)this.occupancyLinks.set(part.link.id,{corridor,...part});
    }
  }
  occupancy(record) {
    const value=record?.Native_Occupancy;let part=this.occupancyLinks?.get(record?.Link_ID);
    if(!value || value.policy!=='corridor-length-v1' ||
       !Number.isSafeInteger(value.ordinal) || value.ordinal<0)return null;
    const reserved=this.occupancyCorridors?.get(value.corridor_id);
    if(!reserved || !Number.isSafeInteger(value.model_slot) || value.model_slot<0 ||
       value.model_slot>=reserved.data.represented_lanes || value.model_slot>=reserved.parts[0].link.lanes)return null;
    if(Array.isArray(value.exit_links) && value.exit_links.includes(record.Link_ID)) {
      const links=value.exit_links.map(id=>this.links.get(id)),slots=value.exit_slots,
        exitIndex=reserved.parts.findIndex(p=>p.link.id===value.exit_from_link),last=reserved.parts[exitIndex];
      if(value.passage_kind!=='boundary_exit' || !last || !Array.isArray(slots) ||
         slots.length!==links.length || links.some((link,i)=>!link?.geometry || !link.eligible ||
         !Number.isSafeInteger(slots[i]) || slots[i]<0 || slots[i]>=link.lanes) ||
         [last.link,...links].some((link,i,all)=>i && !this.connects(all[i-1],link)))return null;
      let offset=last.offset+last.length;
      const suffix=links.map((link,i)=>{const p={link,offset,length:link.geometry.length,slot:slots[i]};offset+=p.length;return p;});
      const corridor={...reserved,parts:[...reserved.parts.slice(0,exitIndex+1),...suffix],length:offset,exitPassage:true};
      part={...suffix.find(p=>p.link.id===record.Link_ID),corridor};
    }
    if(Array.isArray(value.passage_links) && (value.passage_links.includes(record.Link_ID) || part?.corridor.id===value.corridor_id)) {
      const links=value.passage_links.map(id=>this.links.get(id)),slots=value.passage_slots;
      const receiptIndex=reserved.parts.findIndex(p=>p.link.id===value.receipt_link),receipt=reserved.parts[receiptIndex];
      if(!Array.isArray(slots) || slots.length!==links.length || links.some((link,i)=>!link?.geometry || !link.eligible ||
         !Number.isSafeInteger(slots[i]) || slots[i]<0 || slots[i]>=link.lanes) ||
         !receipt || [...links,receipt.link].some((link,i,all)=>i && !this.connects(all[i-1],link)))return null;
      let offset=receipt.offset-links.reduce((sum,link)=>sum+link.geometry.length,0);
      const prefix=links.map((link,i)=>{const p={link,offset,length:link.geometry.length,slot:slots[i]};offset+=p.length;return p;});
      const corridor={...reserved,parts:[...prefix,...reserved.parts.slice(receiptIndex)],passage:true};
      part={...(prefix.find(p=>p.link.id===record.Link_ID) ?? part),corridor};
    }
    if(!part || part.corridor.id!==value.corridor_id)return null;
    const slot=part.slot ?? value.model_slot;
    if(slot>=part.link.lanes)return null;
    return {...part,slot,reservationSlot:value.model_slot,ordinal:value.ordinal,source:value};
  }
  occupancyBody(occupancy,station,length,width,neighbors={}) {
    const anchored=this.occupancyLaneBody(occupancy,station,length,width,neighbors);
    if(anchored)return anchored;
    const corridor=occupancy.corridor;
    let part=corridor.parts.find(p=>station>=p.offset && station<=p.offset+p.length);
    const first=corridor.parts[0],relative=station-first.offset;
    if(!part && relative<0 && relative>=-length/2-(occupancy.releaseSetback ?? 0)-1e-7) {
      const boundary=this.occupancyPredecessor(first.link.id,neighbors),previous=boundary?.previous ?? neighbors.previous,
        current=boundary?.current ?? neighbors.current,prior=this.links.get(previous?.Link_ID);
      // Only the rigid rear extends beyond the active domain. The native front
      // and trip lifetime are not extrapolated; retain that distinction.
      if(prior?.geometry && this.connects(prior,first.link) && this.observedConnection(previous,current)) {
        const priorOccupancy=this.occupancy(previous);
        if(priorOccupancy && priorOccupancy.corridor.id!==corridor.id) {
          const priorPose=this.occupancyBody(priorOccupancy,priorOccupancy.offset+priorOccupancy.length+relative,length,width,
            {current:previous,next:current,resolve:neighbors.resolve,...neighbors.resolve?.(previous)});
          if(priorPose)return {...priorPose,center:station,reference:'estimated_rear_across_recorded_transition'};
        }
        const point=this.place(prior.id,prior.geometry.length+relative,previous.Visual_Lane_Index);
        if(point)return {body:this.rigidBody(point.position,this.headingAt(prior.geometry,prior.geometry.length+relative,length,null,first.link.geometry.edges[0].heading),length,width,prior.geometry),
          center:station,station:prior.geometry.length+relative,displayLink:prior.id,reference:'estimated_rear_across_recorded_transition'};
      }
      if(relative < -length/2-1e-7)return null;
      const point=this.place(first.link.id,0,occupancy.slot),edge=first.link.geometry.edges[0],g=first.link.geometry;
      if(!point)return null;
      const position=[point.position[0]+relative*edge.dx/g.xScale,point.position[1]+relative*edge.dy/g.yScale];
      return {body:this.rigidBody(position,edge.heading,length,width,g),center:station,station:relative,displayLink:first.link.id,
        reference:'estimated_body_straddling_domain_entry'};
    }
    if(!part)return null;
    const at=station-part.offset,point=this.place(part.link.id,at,part.slot ?? occupancy.reservationSlot ?? occupancy.slot);
    if(!point)return null;
    const index=corridor.parts.indexOf(part),prior=this.links.get(neighbors.previous?.Link_ID),
      previous=index ? corridor.parts[index-1].link.geometry.edges.at(-1).heading :
        prior?.geometry && this.observedConnection(neighbors.previous,neighbors.current) ? prior.geometry.edges.at(-1).heading : null,
      next=index+1<corridor.parts.length ? corridor.parts[index+1].link.geometry.edges[0].heading : null;
    return {body:this.rigidBody(point.position,this.headingAt(part.link.geometry,at,length,previous,next),length,width,part.link.geometry),
      center:station,station:at,displayLink:part.link.id,reference:'estimated_front_referenced_corridor_body'};
  }
  occupancyLaneBody(occupancy,station,length,width,neighbors={}) {
    // Native corridor stations refer to a front, not a measured body centre.
    // Keep that front fixed and find the rear on the recorded sequence of lane
    // curves. Averaging the centreline headings at the centre put a long rear
    // into a neighbouring approach when the body spanned several short links.
    // This rigid chord is a display reconstruction, never a new native path.
    const parts=occupancy.corridor.parts,frontStation=station+length/2;
    let index=parts.findIndex(p=>frontStation>=p.offset-1e-7 && frontStation<=p.offset+p.length+1e-7);
    if(index<0)return null;
    const frontPart=parts[index],at=Math.max(0,Math.min(frontPart.length,frontStation-frontPart.offset));
    const slot=part=>part.slot ?? occupancy.reservationSlot ?? occupancy.slot;
    const partFrom=record=>this.occupancyPathPart(record);
    let firstBoundary;
    const beforeFirst=()=>{
      firstBoundary ??= this.occupancyPredecessor(parts[0].link.id,neighbors) || false;
      return firstBoundary && this.observedConnection(firstBoundary.previous,firstBoundary.current) ? partFrom(firstBoundary.previous) : null;
    };
    const afterLast=neighbors.current?.Link_ID===parts.at(-1).link.id &&
      this.observedConnection(neighbors.current,neighbors.next) ? partFrom(neighbors.next) : null;
    const curveFor=(part,before,after)=>this.recordedLaneCurve(part.link,slot(part),
      before?.link,before && slot(before),after?.link,after && slot(after),
      {current:part.slotSource,before:before?.slotSource,after:after?.slotSource});
    const frontCurve=curveFor(frontPart,index ? parts[index-1] : beforeFirst(),parts[index+1] ?? afterLast),g=frontPart.link.geometry;
    if(!frontCurve)return null;
    const front=this.sampleRecordedLaneCurve(frontCurve,at),sourceParts=[];let last=front,rear=null;
    const visit=next=>{
      if(rear)return;
      const dx=next[0]-last[0],dy=next[1]-last[1],a=dx*dx+dy*dy;
      if(a<1e-14)return;
      const x=last[0]-front[0],y=last[1]-front[1],b=2*(x*dx+y*dy),c=x*x+y*y-length*length;
      const discriminant=b*b-4*a*c;
      if(discriminant>=0) {
        const t=(-b+Math.sqrt(discriminant))/(2*a);
        if(t>=-1e-9 && t<=1+1e-9)rear=[last[0]+t*dx,last[1]+t*dy];
      }
      last=next;
    };
    const consume=(part,end,before,after)=>{
      const curve=curveFor(part,before,after);
      if(!curve)return false;
      sourceParts.push({link_id:part.link.id,slot:slot(part),slot_source:part.slotSource ?? 'native_occupancy_slot',
        estimated_lane_joins:curve.joins});
      for(let i=curve.points.length-1;i>=0 && !rear;i--)
        if(curve.stations[i]<=end+1e-7)visit(curve.points[i]);
      return true;
    };
    if(!consume(frontPart,at,index ? parts[index-1] : beforeFirst(),parts[index+1] ?? afterLast))return null;
    for(let i=index-1;i>=0 && !rear;i--) {
      if(!this.targets(parts[i].link,slot(parts[i])).includes(parts[i+1].link.id) ||
         !consume(parts[i],parts[i].length,i ? parts[i-1] : beforeFirst(),parts[i+1]))return null;
    }
    let boundary=!rear ? firstBoundary || this.occupancyPredecessor(parts[0].link.id,neighbors) : null;
    for(let count=0;boundary && !rear && count<128;count++) {
      const {previous,current}=boundary,prior=this.links.get(previous?.Link_ID),next=this.links.get(current?.Link_ID);
      if(!prior?.geometry || !this.connects(prior,next) || !this.observedConnection(previous,current))break;
      const priorPart=partFrom(previous),nextPart=partFrom(current);
      const earlier=this.occupancyPredecessor(prior.id,{current:previous,resolve:neighbors.resolve,...neighbors.resolve?.(previous)});
      if(!priorPart || !consume(priorPart,priorPart.length,earlier && partFrom(earlier.previous),nextPart))return null;
      boundary=earlier;
    }
    if(!rear)return null; // Entry geometry without a full recorded rear retains the documented fallback.
    const position=[g.origin[0]+(front[0]+rear[0])/2/g.xScale,g.origin[1]+(front[1]+rear[1])/2/g.yScale];
    const heading=Math.atan2(front[1]-rear[1],front[0]-rear[0])*180/Math.PI;
    const display=parts.find(p=>station>=p.offset && station<=p.offset+p.length) ?? frontPart;
    const body=this.rigidBody(position,heading,length,width,g);
    body.reconstruction={source:'front_anchored_recorded_lane_chord_v1',positions_observed:false,
      front_link_id:frontPart.link.id,front_link_station_m:at,front_corridor_station_m:frontStation,
      front_position:[...body.path[1]],rear_position:[...body.path[0]],
      dimensions_preserved:true,source_parts:sourceParts};
    return {body,center:station,station:station-display.offset,
      displayLink:display.link.id,reference:'estimated_front_anchored_recorded_lane_chord'};
  }
  occupancyPathPart(record) {
    const link=this.links.get(record?.Link_ID),native=this.occupancy(record);
    const source=native ? 'native_occupancy_slot' : record?.Visual_Lane_Source==='native' ? 'native_lane_event' :
      link?.lanes===1 ? 'unique_effective_lane' : null;
    const index=native?.slot ?? (source==='native_lane_event' ? record.Visual_Lane_Index : source==='unique_effective_lane' ? 0 : null);
    return link?.geometry && Number.isSafeInteger(index) && index>=0 && index<link.lanes ?
      {link,slot:index,slotSource:source,length:link.geometry.length} : null;
  }
  occupancyFrontPath(occupancy,fromCenter,toCenter,length,neighbors={}) {
    if(!occupancy?.corridor?.parts?.length || ![fromCenter,toCenter,length].every(Number.isFinite) || length<=0)return null;
    const from=fromCenter+length/2,to=toCenter+length/2,lo=Math.min(from,to),hi=Math.max(from,to);
    const parts=[...occupancy.corridor.parts],slot=part=>part.slot ?? occupancy.reservationSlot ?? occupancy.slot;
    let boundary=this.occupancyPredecessor(parts[0].link.id,neighbors);
    const preceding=()=>boundary && this.observedConnection(boundary.previous,boundary.current) ?
      this.occupancyPathPart(boundary.previous) : null;
    for(let count=0;lo<parts[0].offset-1e-7 && count<128;count++) {
      const prior=preceding();
      if(!prior || !this.connects(prior.link,parts[0].link))return null;
      parts.unshift({...prior,offset:parts[0].offset-prior.length});
      const previous=boundary.previous;
      boundary=this.occupancyPredecessor(prior.link.id,{current:previous,resolve:neighbors.resolve,...neighbors.resolve?.(previous)});
    }
    if(lo<parts[0].offset-1e-7 || hi>parts.at(-1).offset+parts.at(-1).length+1e-7)return null;
    const after=neighbors.current?.Link_ID===parts.at(-1).link.id && this.observedConnection(neighbors.current,neighbors.next) ?
      this.occupancyPathPart(neighbors.next) : null;
    const path=[],stations=[],sourceParts=[];
    for(let i=0;i<parts.length;i++) {
      const part=parts[i],start=Math.max(lo,part.offset),end=Math.min(hi,part.offset+part.length);
      if(start>end+1e-7)continue;
      const before=i ? parts[i-1] : preceding(),next=parts[i+1] ?? after;
      if(i && !this.targets(parts[i-1].link,slot(parts[i-1])).includes(part.link.id))return null;
      const curve=this.recordedLaneCurve(part.link,slot(part),before?.link,before && slot(before),next?.link,next && slot(next),
        {current:part.slotSource,before:before?.slotSource,after:next?.slotSource});
      if(!curve)return null;
      const local=[start-part.offset,...curve.stations.filter(s=>s>start-part.offset+1e-7 && s<end-part.offset-1e-7),end-part.offset];
      const g=part.link.geometry;
      for(const station of local) {
        const point=this.sampleRecordedLaneCurve(curve,station),position=[g.origin[0]+point[0]/g.xScale,g.origin[1]+point[1]/g.yScale];
        const absolute=part.offset+station;
        if(stations.length && Math.abs(absolute-stations.at(-1))<1e-7) {
          if(Math.hypot((position[0]-path.at(-1)[0])*g.xScale,(position[1]-path.at(-1)[1])*g.yScale)>1e-5)return null;
          continue;
        }
        path.push(position);stations.push(absolute);
      }
      sourceParts.push({link_id:part.link.id,slot:slot(part),slot_source:part.slotSource ?? 'native_occupancy_slot',
        estimated_lane_joins:curve.joins});
    }
    if(!path.length)return null;
    if(from>to){path.reverse();stations.reverse();}
    return {path,stations_m:stations,source:'estimated_recorded_lane_front_path_v1',positions_observed:false,
      from_front_station_m:from,to_front_station_m:to,source_parts:sourceParts};
  }
  recordedLaneJoin(a,i,b,j,fromSource='native_occupancy_slot',toSource='native_occupancy_slot') {
    if(!a || !b || !Number.isSafeInteger(i) || !Number.isSafeInteger(j) || i<0 || i>=a.lanes || j<0 || j>=b.lanes ||
       !this.connects(a,b) || !this.targets(a,i).includes(b.id))return null;
    const key=JSON.stringify([a.id,i,b.id,j,fromSource,toSource]);
    if(this.recordedLaneJoins.has(key))return this.recordedLaneJoins.get(key);
    const left=this.offsetCurve(a.geometry,this.offset(a,i)),right=this.offsetCurve(b.geometry,this.offset(b,j));
    if(!left || !right)return null;
    const end=left.points.at(-1),start=right.points[0],gap=Math.hypot(end[0]-start[0],end[1]-start[1]);
    const u=a.geometry.edges.at(-1),v=b.geometry.edges[0];
    let result=null;
    if(gap>1e-7 && u.dx*v.dx+u.dy*v.dy>-.98) {
      // A native slot pair proves the lateral movement. Join its two existing
      // offsets locally; the span is the endpoint separation, bounded by the
      // available terminal edges. Never move the front's station or event time.
      const before=Math.min(gap,u.length/2),after=Math.min(gap,v.length/2),
        joint=[(end[0]+start[0])/2,(end[1]+start[1])/2];
      const leftPoint=this.sample(a.geometry,1-before/a.geometry.length,this.offset(a,i)).position;
      const rightPoint=this.sample(b.geometry,after/b.geometry.length,this.offset(b,j)).position;
      const g=a.geometry,xy=p=>[(p[0]-g.origin[0])*g.xScale,(p[1]-g.origin[1])*g.yScale],p=xy(leftPoint),q=xy(rightPoint);
      if(before>1e-7 && after>1e-7 && (joint[0]-p[0])*u.dx+(joint[1]-p[1])*u.dy>1e-7 &&
         (q[0]-joint[0])*v.dx+(q[1]-joint[1])*v.dy>1e-7 && this.simple([p,joint,q])) {
        const source=[fromSource,toSource].includes('unique_effective_lane') ?
          'recorded_unique_lane_pair_estimated_lane_join' : 'recorded_native_slot_pair_estimated_lane_join';
        result={before,after,joint,source,fromSource,toSource};
        this.connectorCache.push({Link_ID:a.id,To_Link_ID:b.id,lane_index:i,to_lane_index:j,
          path:[leftPoint,[g.origin[0]+joint[0]/g.xScale,g.origin[1]+joint[1]/g.yScale],rightPoint],
          width_m:Math.min(a.width,b.width)*.82,width_min_pixels:0,cache_version:this.cacheVersion,
          source,from_slot_source:fromSource,to_slot_source:toSource,endpoint_separation_m:gap,
          before_span_m:before,after_span_m:after,positions_observed:false});
      }
    }
    this.recordedLaneJoins.set(key,result);return result;
  }
  recordedLaneCurve(link,index,before,beforeIndex,after,afterIndex,slotSources={}) {
    const source=slotSources.current ?? 'native_occupancy_slot',beforeSource=slotSources.before ?? 'native_occupancy_slot',
      afterSource=slotSources.after ?? 'native_occupancy_slot';
    const key=JSON.stringify([link.id,index,before?.id,beforeIndex,after?.id,afterIndex,source,beforeSource,afterSource]);
    if(this.recordedLaneCurves.has(key))return this.recordedLaneCurves.get(key);
    const g=link.geometry,base=this.offsetCurve(g,this.offset(link,index));
    if(!base)return null;
    const start=this.recordedLaneJoin(before,beforeIndex,link,index,beforeSource,source),
      end=this.recordedLaneJoin(link,index,after,afterIndex,source,afterSource);
    const stations=new Set(g.distances);
    if(start)stations.add(start.after);
    if(end)stations.add(g.length-end.before);
    const ordered=[...stations].sort((a,b)=>a-b),points=ordered.map(at=>{
      if(start && at<start.after) {
        const p=this.sample(g,start.after/g.length,this.offset(link,index)).position;
        const q=[(p[0]-g.origin[0])*g.xScale,(p[1]-g.origin[1])*g.yScale],t=at/start.after;
        return start.joint.map((value,k)=>value+(q[k]-value)*t);
      }
      if(end && at>g.length-end.before) {
        const p=this.sample(g,1-end.before/g.length,this.offset(link,index)).position;
        const q=[(p[0]-g.origin[0])*g.xScale,(p[1]-g.origin[1])*g.yScale],t=(at-g.length+end.before)/end.before;
        return q.map((value,k)=>value+(end.joint[k]-value)*t);
      }
      const p=this.sample(g,at/g.length,this.offset(link,index)).position;
      return [(p[0]-g.origin[0])*g.xScale,(p[1]-g.origin[1])*g.yScale];
    });
    const joins=[];
    if(start)joins.push({from_link:before.id,from_slot:beforeIndex,to_link:link.id,to_slot:index,
      source:start.source,from_slot_source:start.fromSource,to_slot_source:start.toSource,before_span_m:start.before,after_span_m:start.after});
    if(end)joins.push({from_link:link.id,from_slot:index,to_link:after.id,to_slot:afterIndex,
      source:end.source,from_slot_source:end.fromSource,to_slot_source:end.toSource,before_span_m:end.before,after_span_m:end.after});
    const curve={points,stations:ordered,joins};this.recordedLaneCurves.set(key,curve);return curve;
  }
  sampleRecordedLaneCurve(curve,at) {
    let index=0;while(index<curve.stations.length-2 && curve.stations[index+1]<at)index++;
    const a=curve.stations[index],b=curve.stations[index+1],t=Math.max(0,Math.min(1,(at-a)/(b-a)));
    return curve.points[index].map((value,k)=>value+(curve.points[index+1][k]-value)*t);
  }
  occupancyPredecessor(firstId,neighbors) {
    // The centre/rear may still be in the old corridor after the native front
    // has already crossed two short members of the new one. Follow the same
    // validated interval closure used by queues, not just the immediate link.
    let current=neighbors.current,previous=neighbors.previous;
    const seen=new Set();
    for(let count=0;current && count<128;count++) {
      const key=JSON.stringify([current.Link_ID,current.timestamps]);
      if(seen.has(key))return null;seen.add(key);
      previous=neighbors.resolve?.(current)?.previous ?? previous;
      if(!previous)return null;
      if(current.Link_ID===firstId && previous.Link_ID!==firstId)return {previous,current};
      if(previous.vehicle!==current.vehicle || previous.Agent_ID!==current.Agent_ID ||
         previous.Replay_Journey_Key!==current.Replay_Journey_Key || previous.timestamps?.[1]!==current.timestamps?.[0])return null;
      if(!neighbors.resolve)return null;
      current=previous;previous=null;
    }
    return null;
  }
  validPoint(p) {
    return Array.isArray(p) && p.length>=2 && Number.isFinite(p[0]) && Number.isFinite(p[1]) &&
      Math.abs(p[0])<=180 && Math.abs(p[1])<85;
  }
  setProjection(origin) {
    const metresPerDegree=6371008.8*Math.PI/180;
    this.projection={origin:[...origin],xScale:metresPerDegree*Math.cos(origin[1]*Math.PI/180),yScale:metresPerDegree};
  }
  geometry(path) {
    if(!Array.isArray(path) || path.length<2)return null;
    if(this.paths.has(path))return this.paths.get(path);
    const valid=path.every(p=>this.validPoint(p));
    if(!valid){this.paths.set(path,null);return null;}
    if(!this.projection)this.setProjection(path[0]);
    const {origin,xScale,yScale}=this.projection;
    const points=[],distances=[0],edges=[];
    for(const p of path) {
      const point=[(p[0]-origin[0])*xScale,(p[1]-origin[1])*yScale];
      const previous=points[points.length-1];
      if(previous && Math.hypot(point[0]-previous[0],point[1]-previous[1])<1e-7)continue;
      if(previous) {
        const dx=point[0]-previous[0],dy=point[1]-previous[1],length=Math.hypot(dx,dy);
        if(!Number.isFinite(length) || length>100000){this.paths.set(path,null);return null;}
        edges.push({dx:dx/length,dy:dy/length,length,heading:Math.atan2(dy,dx)*180/Math.PI});
        distances.push(distances[distances.length-1]+length);
      }
      points.push(point);
    }
    if(points.length<2){this.paths.set(path,null);return null;}
    const length=distances[distances.length-1];
    const geometry={points,distances,edges,length,origin,xScale,yScale,offsets:new Map(),joins:{}};
    this.paths.set(path,geometry);return geometry;
  }
  joinVector(before,after) {
    // Intersection of two parallel-offset lines (right normals dy,-dx).
    // Reject unbounded mitres instead of tapering, rounding or reversing a lane.
    const denominator=1+before.dx*after.dx+before.dy*after.dy;
    if(denominator<1e-8)return null;
    const v=[(before.dy+after.dy)/denominator,-(before.dx+after.dx)/denominator];
    return Math.hypot(...v)<=4 ? v : null;
  }
  simple(points,closed=false) {
    const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
    for(let i=1;i<points.length;i++)for(let j=i+2;j<points.length;j++) {
      if(closed && i===1 && j===points.length-1)continue; // Adjacent across the closing vertex.
      const a=points[i-1],b=points[i],c=points[j-1],d=points[j];
      if(Math.max(a[0],b[0])+1e-8<Math.min(c[0],d[0]) || Math.max(c[0],d[0])+1e-8<Math.min(a[0],b[0]) ||
         Math.max(a[1],b[1])+1e-8<Math.min(c[1],d[1]) || Math.max(c[1],d[1])+1e-8<Math.min(a[1],b[1]))continue;
      if(cross(a,b,c)*cross(a,b,d)<=1e-12 && cross(c,d,a)*cross(c,d,b)<=1e-12)return false;
    }
    return true;
  }
  offsetCurve(geometry,offset) {
    if(geometry.offsets.has(offset))return geometry.offsets.get(offset);
    const points=[];
    for(let i=0;i<geometry.points.length;i++) {
      const before=geometry.edges[Math.max(0,i-1)],after=geometry.edges[Math.min(i,geometry.edges.length-1)];
      const normal=offset===0 ? [0,0] : i===0 ? geometry.joins.start || [after.dy,-after.dx] :
        i===geometry.points.length-1 ? geometry.joins.end || [before.dy,-before.dx] : this.joinVector(before,after);
      if(!normal){geometry.offsets.set(offset,null);return null;}
      points.push([geometry.points[i][0]+offset*normal[0],geometry.points[i][1]+offset*normal[1]]);
    }
    const forward=geometry.edges.every((edge,i)=>(points[i+1][0]-points[i][0])*edge.dx+
      (points[i+1][1]-points[i][1])*edge.dy>1e-7);
    const result=forward && (offset===0 || this.simple(points)) ? {points} : null;
    geometry.offsets.set(offset,result);return result;
  }
  smooth(value) { const t=Math.max(0,Math.min(1,value));return t*t*(3-2*t); }
  sample(geometry,fraction,offset) {
    const curve=this.offsetCurve(geometry,offset);
    if(!curve)return null;
    const distance=Math.max(0,Math.min(1,fraction))*geometry.length;
    let low=0,high=geometry.edges.length;
    while(low<high){const mid=(low+high)>>>1;if(geometry.distances[mid+1]<=distance)low=mid+1;else high=mid;}
    const index=Math.min(low,geometry.edges.length-1),edge=geometry.edges[index];
    const along=(distance-geometry.distances[index])/edge.length,a=curve.points[index],b=curve.points[index+1];
    const x=a[0]+(b[0]-a[0])*along,y=a[1]+(b[1]-a[1])*along;
    return {position:[geometry.origin[0]+x/geometry.xScale,geometry.origin[1]+y/geometry.yScale],offset,factor:1};
  }
  lateralScale(link) { return 1; } // Short subdivisions do not change road width.
  offset(link,index) {
    return (link.opposing ? index+(link.opposing-link.lanes+1)/2 : index-(link.lanes-1)/2)*link.width*this.lateralScale(link);
  }
  stableIndex(vehicle,id,lanes) {
    let hash=2166136261;
    const key=this.links.get(id)?.assignmentKey ?? id;
    for(const char of String(vehicle)+'\u0000'+key){hash^=char.charCodeAt(0);hash=Math.imul(hash,16777619);}
    return (hash>>>0)%lanes;
  }
  compatibleLevel(a,b) {
    return ['bridge','tunnel','layer'].every(key=>a.data.osm_tags?.[key]===b.data.osm_tags?.[key]);
  }
  targets(link,index) {
    const observed=Object.values(link.data.native_lanes || {}).filter(lane=>lane.index===index &&
      lane.represented_lanes===1 && Array.isArray(lane.to_links));
    if(observed.length===1)return observed[0].to_links;
    return ['effective_car_node_adjacency','effective_mode_node_adjacency'].includes(link.data.movement_source) && Array.isArray(link.data.allowed_to_links) ?
      link.data.allowed_to_links : [];
  }
  connects(a,b) {
    if(!a?.eligible || !b?.eligible || !a.geometry || !b.geometry ||
       a.data.to_node==null || a.data.to_node!==b.data.from_node || !this.compatibleLevel(a,b))return false;
    const end=a.geometry.points[a.geometry.points.length-1],start=b.geometry.points[0];
    return Math.hypot(end[0]-start[0],end[1]-start[1])<1e-5;
  }
  sameSection(a,b) {
    return a.data.source_way!=null && a.data.source_way===b.data.source_way &&
      a.lanes===b.lanes && a.opposing===b.opposing && Math.abs(a.width-b.width)<1e-7;
  }
  insetConnector(a,b,i,j) {
    // A right-side offset can put node endpoints behind the turning tangent.
    // Only an unambiguous, already permitted single-lane movement may receive
    // this small schematic curve. It does not supply any vehicle trajectory.
    if(a.lanes!==1 || b.lanes!==1 || !this.connects(a,b) || !this.targets(a,i).includes(b.id) ||
       a.data.from_node===b.data.to_node)return null;
    const before=a.geometry.edges.at(-1),after=b.geometry.edges[0];
    const dot=before.dx*after.dx+before.dy*after.dy;
    if(dot<=-.95 || dot>=.95)return null; // No inferred U-turns or lane merges.
    const setback=2*(Math.max(Math.abs(this.offset(a,i)),Math.abs(this.offset(b,j)))+.25);
    if(setback>before.length*.5 || setback>after.length*.5)return null;
    const first=this.sample(a.geometry,1-setback/a.geometry.length,this.offset(a,i))?.position;
    const last=this.sample(b.geometry,setback/b.geometry.length,this.offset(b,j))?.position;
    if(!first || !last)return null;
    const g=a.geometry,toXY=p=>[(p[0]-g.origin[0])*g.xScale,(p[1]-g.origin[1])*g.yScale];
    const p0=toXY(first),p3=toXY(last),handle=setback*.5;
    const p1=[p0[0]+before.dx*handle,p0[1]+before.dy*handle];
    const p2=[p3[0]-after.dx*handle,p3[1]-after.dy*handle];
    const points=[];
    for(let step=0;step<=12;step++) {
      const t=step/12,u=1-t;
      points.push([0,1].map(k=>u*u*u*p0[k]+3*u*u*t*p1[k]+3*u*t*t*p2[k]+t*t*t*p3[k]));
    }
    // Progress along the turn's bisector must remain positive: no retraced hook.
    if(!this.simple(points) || points.slice(1).some((p,k)=>
      (p[0]-points[k][0])*(before.dx+after.dx)+(p[1]-points[k][1])*(before.dy+after.dy)<=1e-7))return null;
    return {path:points.map(p=>[g.origin[0]+p[0]/g.xScale,g.origin[1]+p[1]/g.yScale]),
      source:'permitted_single_lane_turn_schematic',setback_m:setback,setback_source:'inferred_visual_only'};
  }
  safeSection(link) {
    // Validate both borders too: a safe centreline alone can hide an inverted strip.
    for(let index=0;index<link.lanes;index++) {
      const offset=this.offset(link,index);
      for(const value of [offset,offset-link.width*.41,offset+link.width*.41])
        if(!this.offsetCurve(link.geometry,value))return false;
    }
    return true;
  }
  safeChain(chain,closed) {
    // A locally safe offset can cross a distant part of the same joined road.
    // Check centres and borders once in the common metric plane, after all joins.
    const first=chain[0];
    for(let index=0;index<first.lanes;index++) {
      const offset=this.offset(first,index);
      for(const value of [offset,offset-first.width*.41,offset+first.width*.41]) {
        const points=[];
        for(const link of chain) {
          const curve=this.offsetCurve(link.geometry,value);
          if(!curve)return false;
          for(let i=points.length ? 1 : 0;i<curve.points.length;i++)points.push(curve.points[i]);
        }
        if(!this.simple(points,closed))return false;
      }
    }
    return true;
  }
  prepareGeometry() {
    const incoming=new Map(),outgoing=new Map(),parent=new Map(),joinedNext=new Map(),joinedPrevious=new Map();
    const add=(map,key,link)=>{if(key==null)return;if(!map.has(key))map.set(key,[]);map.get(key).push(link);};
    const root=id=>{let r=id;while(parent.get(r)!==r)r=parent.get(r);return r;};
    for(const [id,link] of this.links) {
      parent.set(id,id);
      if(link.eligible && link.geometry && !this.safeSection(link)) {
        link.eligible=false;this.geometryIssues.push({Link_ID:id,reason:'unsafe_parallel_offset_native_axis_retained'});
      }
      add(incoming,link.data.to_node,link);add(outgoing,link.data.from_node,link);
    }
    const continuation=(a,b)=>this.connects(a,b) && this.sameSection(a,b) &&
      b.data.to_node!==a.data.from_node && Array.from({length:a.lanes},(_,i)=>i).every(i=>this.targets(a,i).includes(b.id));
    for(const a of [...this.links.values()].sort((x,y)=>x.id.localeCompare(y.id))) {
      const next=(outgoing.get(a.data.to_node) || []).filter(b=>continuation(a,b));
      if(next.length!==1)continue;
      const b=next[0];
      if((incoming.get(b.data.from_node) || []).filter(p=>continuation(p,b)).length!==1)continue;
      const vector=this.joinVector(a.geometry.edges[a.geometry.edges.length-1],b.geometry.edges[0]);
      if(!vector)continue;
      a.geometry.joins.end=vector;b.geometry.joins.start=vector;
      a.geometry.offsets.clear();b.geometry.offsets.clear();
      if(!this.safeSection(a) || !this.safeSection(b)) {
        delete a.geometry.joins.end;delete b.geometry.joins.start;
        a.geometry.offsets.clear();b.geometry.offsets.clear();
        this.geometryIssues.push({Link_ID:a.id,To_Link_ID:b.id,reason:'unsafe_joint_not_stitched'});
        continue;
      }
      joinedNext.set(a.id,b.id);joinedPrevious.set(b.id,a.id);
      const left=root(a.id),right=root(b.id);parent.set(left<right ? right : left,left<right ? left : right);
    }
    const chains=new Map();
    for(const link of this.links.values())add(chains,root(link.id),link);
    for(const members of chains.values()) {
      if(members.length<2)continue;
      const start=members.find(link=>!joinedPrevious.has(link.id)) || members.find(link=>link.id===root(link.id));
      const chain=[],seen=new Set();let link=start;
      while(link && !seen.has(link.id)) {
        chain.push(link);seen.add(link.id);link=this.links.get(joinedNext.get(link.id));
      }
      if(this.safeChain(chain,link?.id===start.id))continue;
      for(const member of chain) {
        member.eligible=false;member.geometry.joins={};member.geometry.offsets.clear();
      }
      this.geometryIssues.push({Link_ID:start.id,Link_IDs:chain.map(member=>member.id),
        reason:'unsafe_joined_offset_native_axes_retained'});
    }
    for(const [id,link] of this.links) {
      link.assignmentKey=root(id);
      if(!link.geometry)continue;
      if(!link.eligible) {
        this.roadCache.push({Link_ID:id,lane_index:null,path:link.data.path.map(point=>point.slice(0,2)),
          width_m:link.width*.82,width_min_pixels:0,source:'centerline'});
        continue;
      }
      const geometry=link.geometry,stations=new Set(geometry.distances);
      for(let i=0;i<geometry.edges.length;i++)stations.add((geometry.distances[i]+geometry.distances[i+1])/2);
      const ordered=[...stations].sort((a,b)=>a-b);
      for(let index=0;index<link.lanes;index++)this.roadCache.push({Link_ID:id,lane_index:index,
        path:ordered.map(at=>this.sample(geometry,at/geometry.length,this.offset(link,index)).position),
        width_m:link.width*.82,width_min_pixels:0,source:'estimated_parallel_geometry',cache_version:this.cacheVersion});
      this.offsetCurve(geometry,0);
    }
    // Connectors depict permitted movements only; they are never sampled by
    // marker(), place() or body(), and never supply new vehicle timestamps.
    for(const a of this.links.values())if(a.eligible && a.geometry)for(let i=0;i<a.lanes;i++) {
      for(const target of new Set(this.targets(a,i))) {
        const b=this.links.get(target);
        if(!this.connects(a,b))continue;
        const j=b.lanes===1 ? 0 : a.assignmentKey===b.assignmentKey ? i : null;
        if(j==null){this.ambiguousConnectors++;continue;} // toLink does not identify a target lane.
        const start=this.sample(a.geometry,1,this.offset(a,i)).position,end=this.sample(b.geometry,0,this.offset(b,j)).position;
        const dx=(end[0]-start[0])*a.geometry.xScale,dy=(end[1]-start[1])*a.geometry.yScale;
        if(Math.hypot(dx,dy)<1e-5)continue;
        const before=a.geometry.edges[a.geometry.edges.length-1],after=b.geometry.edges[0];
        if(dx*before.dx+dy*before.dy < -1e-7 || dx*after.dx+dy*after.dy < -1e-7) {
          const inset=this.insetConnector(a,b,i,j);
          if(inset) {
            this.connectorCache.push({Link_ID:a.id,To_Link_ID:b.id,lane_index:i,to_lane_index:j,
              ...inset,width_m:Math.min(a.width,b.width)*.82,width_min_pixels:0,cache_version:this.cacheVersion});
            this.insetConnectors++;
          } else {
            this.reversingConnectors++;
            this.geometryIssues.push({Link_ID:a.id,To_Link_ID:b.id,lane_index:i,to_lane_index:j,
              reason:'reversing_visual_connector_without_supported_curve'});
          }
          continue; // Never render the retraced straight connector.
        }
        this.connectorCache.push({Link_ID:a.id,To_Link_ID:b.id,lane_index:i,to_lane_index:j,path:[start,end],
          width_m:Math.min(a.width,b.width)*.82,width_min_pixels:0,source:'permitted_movement_schematic',cache_version:this.cacheVersion});
      }
    }
  }
  connectors() { return this.connectorCache; }
  snapshot() {
    return {version:this.cacheVersion,units:'local_metres',persistence:'memory_only',
      roads:this.roadCache.length,connectors:this.connectorCache.length,
      ambiguousTargetLaneMovements:this.ambiguousConnectors,reversingConnectorsOmitted:this.reversingConnectors,
      inferredSingleLaneTurnConnectors:this.insetConnectors,
      issues:this.geometryIssues};
  }
  compatiblePath(link,path) {
    if(!link || !Array.isArray(path))return false;
    let cached=this.pathCompatibility.get(path);
    if(cached?.has(link))return cached.get(link);
    const compatible=this.checkCompatiblePath(link,path);
    if(!cached){cached=new Map();this.pathCompatibility.set(path,cached);}cached.set(link,compatible);return compatible;
  }
  checkCompatiblePath(link,path) {
    const geometry=link?.geometry;
    if(!geometry || !Array.isArray(path) || path.length<2 || !path.every(p=>this.validPoint(p)))return false;
    const endpoints=[path[0],path[path.length-1]],native=[link.data.path[0],link.data.path[link.data.path.length-1]];
    const distance=(a,b)=>Math.hypot((a[0]-b[0])*geometry.xScale,(a[1]-b[1])*geometry.yScale);
    const ordered=endpoints.map((p,i)=>distance(p,native[i]));
    // The 25 cm coordinate tolerance alone accepts reversed short links.
    // Require a uniquely better ordered match; ambiguity preserves the supplied path.
    const reversed=distance(endpoints[0],native[1])+distance(endpoints[1],native[0]);
    return ordered.every(value=>value<=.25) && ordered[0]+ordered[1]+1e-7<reversed;
  }
  nativeFacilityPose(segment) {
    const link=this.links.get(segment?.Link_ID),path=segment?.path,boundary=segment?.Boundary_Provenance,
      transit=segment?.Trip?.Transit,[start,end]=segment?.timestamps || [],fraction=boundary?.start_relative;
    if(!link?.geometry || !Array.isArray(path) || path.length!==2 || !path.every(p=>this.validPoint(p)) ||
       path[0][0]!==path[1][0] || path[0][1]!==path[1][1] || !(Number.isFinite(start) && Number.isFinite(end) && start<end) ||
       boundary?.start!=='VehicleArrivesAtFacility' || boundary?.end!=='VehicleDepartsAtFacility' ||
       !Number.isFinite(fraction) || fraction<0 || fraction>1 || boundary.end_relative!==fraction ||
       segment.Motion_Plan?.status!=='stationary' || segment.Motion_Plan.distance_m!==0 ||
       transit?.schema!=='simz1-transit-replay-v1' || transit.vehicle_id!==segment.vehicle)return null;
    const stop=transit.activity_intervals?.find(row=>row.state==='stop' && row.source==='native_facility_events' &&
      row.start===start && row.end===end && row.link_id===segment.Link_ID && row.relative_position===fraction &&
      ['native_lane_membership_and_verified_lane_endpoint','MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment'].includes(row.position_source));
    return this.nativeFacilityEndpoint(segment,stop,path[0]);
  }
  nativeFacilityEndpoint(segment,stop,position) {
    const link=this.links.get(segment?.Link_ID),transit=segment?.Trip?.Transit,fraction=stop?.relative_position;
    if(!link?.geometry || transit?.schema!=='simz1-transit-replay-v1' || transit.vehicle_id!==segment.vehicle ||
       !stop || stop.state!=='stop' || stop.source!=='native_facility_events' || stop.link_id!==segment.Link_ID ||
       !['native_lane_membership_and_verified_lane_endpoint','MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment'].includes(stop.position_source) ||
       !Number.isFinite(fraction) || fraction<0 || fraction>1 || !this.validPoint(position))return null;
    const single=stop.position_source==='MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment';
    if(single && (link.lanes!==1 || Object.keys(link.data.native_lanes || {}).length || fraction!==1))return null;
    const native=single ? {start_m:link.data.length_m,to_lanes:[]} : stop && link.data.native_lanes?.[stop.lane_id],length=link.data.length_m;
    if(!native || !Number.isFinite(length) || length<=0 || !Number.isFinite(native.start_m) ||
       native.start_m<=0 || native.start_m>length)return null;
    const next=(native.to_lanes || []).map(id=>link.data.native_lanes?.[id]);
    // A facility at a serial lane endpoint is not necessarily at the link end.
    // Recheck that endpoint from the fingerprinted native lane lengths. A fork
    // with unequal downstream extents does not locate a unique stationary point.
    if(next.some(row=>!row || !Number.isFinite(row.start_m) || row.start_m<=0 || row.start_m>=native.start_m) ||
       next.some(row=>Math.abs(row.start_m-next[0].start_m)>1e-7))return null;
    const expected=next.length ? (length-next[0].start_m)/length : 1;
    if(Math.abs(fraction-expected)>1e-9)return null;
    const point=this.sample(link.geometry,fraction,0)?.position;
    if(!point || Math.hypot((point[0]-position[0])*link.geometry.xScale,
                           (point[1]-position[1])*link.geometry.yScale)>.25)return null;
    return {position:[...position],fraction,station_m:fraction*link.geometry.length,
      facility_id:stop.facility_id,lane_id:stop.lane_id,
      blocking_queue:stop.is_blocking_lane===true,
      source:'native_facility_interval_and_verified_lane_endpoint',
      orientation_source:'estimated_local_network_tangent',lateral_position_observed:false};
  }
  recordedBoundaryPath(segment) {
    const link=this.links.get(segment?.Link_ID),b=segment?.Boundary_Provenance,path=segment?.path,
      [start,end]=segment?.timestamps || [],from=b?.start_relative,to=b?.end_relative,plan=segment?.Motion_Plan;
    if(!link?.geometry || !Array.isArray(path) || path.length!==2 || !path.every(p=>this.validPoint(p)) ||
       ![start,end,from,to].every(Number.isFinite) || start>=end || from<0 || to>1 || from>to ||
       b.distance!=='network_length_fraction' || !Number.isFinite(link.data.length_m) || link.data.length_m<=0 ||
       !plan || plan.status==='unavailable' || !Number.isFinite(plan.distance_m) ||
       Math.abs(plan.distance_m-(to-from)*link.data.length_m)>1e-6*Math.max(1,link.data.length_m))return null;
    for(const [position,fraction] of [[path[0],from],[path[1],to]]) {
      const point=this.sample(link.geometry,fraction,0)?.position;
      if(!point || Math.hypot((point[0]-position[0])*link.geometry.xScale,
                             (point[1]-position[1])*link.geometry.yScale)>.25)return null;
    }
    const facility=(time,fraction,position,atArrival)=>segment.Trip?.Transit?.activity_intervals?.some(stop=>
      (atArrival ? stop.start : stop.end)===time && stop.relative_position===fraction &&
      this.nativeFacilityEndpoint(segment,stop,position));
    const observedStart=b.start==='entered link' && from===0 || b.start==='vehicle enters traffic' ||
      b.start==='VehicleDepartsAtFacility' && facility(start,from,path[0],false);
    const observedEnd=b.end==='left link' && to===1 || b.end==='vehicle leaves traffic' ||
      b.end==='VehicleArrivesAtFacility' && facility(end,to,path[1],true);
    if(!observedStart || !observedEnd)return null;
    return {source:'native_boundary_fractions_and_validated_visual_motion',start_event:b.start,end_event:b.end,
      start_relative:from,end_relative:to,continuous_position_observed:false,
      position_basis:from===to ? 'fixed_recorded_boundary_position' : 'interpolated_within_recorded_boundary_path',
      lateral_position_observed:false,orientation_source:'estimated_recorded_path_tangent'};
  }
  nativeQueueDomain(link,segment,observation) {
    const event=observation?.event,lane=observation?.lane,[start,end]=segment.timestamps || [];
    const native=typeof lane==='string' ? link.data.native_lanes?.[lane] : null;
    const at=observation?.observed_at;
    if(!Number.isFinite(start) || !Number.isFinite(end) || end<=start ||
       !native || event?.type!=='entered lane' || event.link!==link.id || event.lane!==lane ||
       event.vehicle!==segment.vehicle || !Number.isFinite(event.time) || event.time<start || event.time>=end ||
       !Number.isFinite(at) || event.time>at || at<start || at>end)return null;
    const length=link.data.length_m,shared=native.index==null && Array.isArray(native.to_lanes) && native.to_lanes.length>0;
    const result={lane_id:lane,event_time:event.time,kind:shared ? 'shared_upstream' : 'terminal',
      source:'effective_native_lane_serial_geometry',available:false};
    if(!(Number.isFinite(length) && length>0 && Number.isFinite(native.start_m) && native.start_m>0 && native.start_m<=length))
      return {...result,reason:'native_lane_extent_unavailable'};
    let from=length-native.start_m,to=length;
    if(shared) {
      const targets=native.to_lanes.map(id=>link.data.native_lanes[id]),starts=targets.map(row=>row?.start_m);
      if(native.represented_lanes!==link.lanes || native.to_lanes.length!==link.lanes ||
         new Set(native.to_lanes).size!==link.lanes || targets.some(row=>!row || row.represented_lanes!==1 ||
           !Number.isSafeInteger(row.index) || row.index<0 || row.index>=link.lanes || (row.to_lanes || []).length) ||
         new Set(targets.map(row=>row?.index)).size!==link.lanes || starts.some(value=>
           !Number.isFinite(value) || value<=0 || value>=native.start_m || Math.abs(value-starts[0])>1e-7))
        return {...result,reason:'ambiguous_serial_lane_extent'};
      // MATSim 15 LanesUtils.createLanes: an upstream lane's length is its
      // startsAt minus the next lane's startsAt, not startsAt itself.
      to=length-starts[0];
    } else if(!Number.isSafeInteger(native.index) || native.index<0 || native.index>=link.lanes || native.represented_lanes!==1 ||
              (native.to_lanes || []).length)return {...result,reason:'ambiguous_terminal_lane_extent'};
    return {...result,available:true,native_length_m:length,from_m:from,to_m:to,
      geometry_from_m:from/length*link.geometry.length,geometry_to_m:to/length*link.geometry.length};
  }
  marker(segment,fraction,observation={},centerPosition) {
    const id=segment?.Link_ID,link=this.links.get(id);
    const radius=link?.geometry ? Math.min(.8,link.width*.3) : .8;
    const fallback=(reason,position=centerPosition)=>({position:Array.isArray(position) ? [...position] : position,
      Visual_Lane_Index:null,Visual_Lane_Source:'centerline',Visual_Lane_Offset_Meters:0,
      Visual_Lane_Marker_Radius_Meters:radius,Visual_Lane_Reason:reason});
    if(!link)return fallback('Sin geometria de carriles validada para este enlace');
    const geometry=link.geometry,path=segment.path;
    if(!geometry || !Number.isFinite(fraction) || !Array.isArray(path) || path.length<2 ||
       !path.every(p=>Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0])<=180 && Math.abs(p[1])<85))
      return fallback('Geometria degenerada o fraccion no disponible; se conserva el eje');
    const facility=this.nativeFacilityPose(segment),occupancy=this.occupancy(segment);
    if(facility)return {...fallback('Punto nativo de servicio; huella geometrica estimada',facility.position),
      Visual_Native_Facility_Position:facility,...(occupancy ? {Visual_Lane_Index:occupancy.slot,Visual_Lane_Source:'native_modeled_occupancy_slot'} : {})};
    if(!occupancy && !this.compatiblePath(link,path))
      return fallback('Extremos o direccion del tramo incompatibles con el enlace validado');
    const bounded=Math.max(0,Math.min(1,fraction));
    if(!link.eligible)return fallback('Offset no disponible; se conserva la geometria efectiva del eje',
      this.sample(geometry,bounded,0)?.position ?? centerPosition);
    const domain=this.nativeQueueDomain(link,segment,observation);
    const station=bounded*geometry.length,projected=domain?.available ?
      Math.max(domain.geometry_from_m,Math.min(domain.geometry_to_m,station)) : station;
    const projection=domain?.available ? {applied:Math.abs(projected-station)>1e-7,
      source:'estimated_queue_extent_projection',source_station_m:bounded*domain.native_length_m,
      projected_station_m:projected/geometry.length*domain.native_length_m,
      source_position:this.sample(geometry,bounded,0)?.position,projected_position:this.sample(geometry,projected/geometry.length,0)?.position,
      continuous_position_observed:false} : null;
    const queueFields=domain ? {Visual_Native_Queue_Kind:domain.kind,Visual_Native_Queue_Extent:domain,
      Visual_Native_Queue_Station_Meters:projected,Visual_Queue_Extent_Projection:projection} : {};
    if(occupancy) {
      const boundary=segment.Boundary_Provenance,f0=boundary?.start_relative ?? 0,f1=boundary?.end_relative ?? 1;
      if(![f0,f1].every(Number.isFinite) || f0<0 || f1<f0 || f1>1)return fallback('Intervalo relativo no verificable');
      const point=this.sample(geometry,f0+bounded*(f1-f0),this.offset(link,occupancy.slot));
      return {position:point.position,Visual_Lane_Index:occupancy.slot,Visual_Lane_Source:'native_modeled_occupancy_slot',
        ...queueFields,Visual_Lane_Offset_Meters:point.offset,Visual_Lane_Width_Meters:link.width*this.lateralScale(link),
        Visual_Lane_Marker_Radius_Meters:radius,Visual_Lane_Reason:'Slot reservado por el adaptador; posicion lateral estimada, no medida'};
    }
    if(domain?.kind==='shared_upstream')return {...fallback('Cola nativa compartida: dominio longitudinal respaldado; carril lateral no observado',
      this.sample(geometry,projected/geometry.length,0)?.position ?? centerPosition),...queueFields};
    const lane=observation?.lane,event=observation?.event;
    const native=typeof lane==='string' && link.data.native_lanes &&
      Object.prototype.hasOwnProperty.call(link.data.native_lanes,lane) ? link.data.native_lanes[lane] : null;
    const length=Number.isFinite(link.data.length_m) && link.data.length_m>0 ? link.data.length_m : geometry.length;
    const uniquelyObserved=native && Number.isSafeInteger(native.index) && native.index>=0 && native.index<link.lanes &&
      native.represented_lanes===1 && Number.isFinite(native.start_m) && native.start_m>0 &&
      native.start_m<=length+1e-7 && event?.type==='entered lane' && event.link===id && event.lane===lane &&
      event.vehicle===segment.vehicle && Number.isFinite(event.time) && event.time>=segment.timestamps?.[0] &&
      event.time<segment.timestamps?.[1] && (!Number.isFinite(observation.observed_at) || event.time<=observation.observed_at);
    let index,source,reason;
    if(uniquelyObserved) {
      index=native.index;source='native';reason='Carril nativo identificado; posicion lateral estimada';
    } else {
      if(segment.vehicle==null)return fallback('Sin identidad estable de vehiculo para asignacion visual');
      const next=observation?.next_segment;
      const connected=next && this.observedConnection(segment,next);
      const candidates=Array.from({length:link.lanes},(_,i)=>i).filter(i=>!connected || this.targets(link,i).includes(next.Link_ID));
      if(!candidates.length)return fallback('Sin carril compatible con el siguiente enlace observado');
      index=candidates[this.stableIndex(segment.vehicle,id,candidates.length)];source='estimated';
      reason=connected ? 'Carril estimado entre los permitidos hacia el siguiente enlace observado' :
        'Sin carril nativo unico aplicable; asignacion visual estable en subdivisiones compatibles';
    }
    const point=this.sample(geometry,projected/geometry.length,this.offset(link,index));
    if(!point)return fallback('Offset paralelo no representable; se conserva el eje');
    if(link.lanes===1 && !link.opposing && !uniquelyObserved) {
      source='centerline';reason='Enlace de un carril y un sentido; se conserva el eje';
    }
    return {position:point.position,Visual_Lane_Index:index,Visual_Lane_Source:source,...queueFields,
      Visual_Lane_Offset_Meters:point.offset,Visual_Lane_Width_Meters:link.width*this.lateralScale(link),
      Visual_Lane_Marker_Radius_Meters:radius,Visual_Lane_Reason:reason};
  }
  describe(id) {
    if(this.descriptions.has(id))return this.descriptions.get(id);
    const link=this.links.get(id);
    const result=link?.geometry ? {length_m:link.geometry.length,lane_count:link.lanes,
      eligible:link.eligible,lane_width_m:link.width*this.lateralScale(link)} : null;
    if(link)this.descriptions.set(id,result);return result;
  }
  storage(id,index,nativeLane) {
    const link=this.links.get(id);
    if(!link?.geometry)return null;
    const effectiveLength=Number.isFinite(link.data.length_m) && link.data.length_m>0 ?
      Math.min(link.geometry.length,link.data.length_m) : link.geometry.length;
    const mapped=typeof nativeLane==='string' ? link.data.native_lanes?.[nativeLane] : null;
    const key=JSON.stringify([id,index,mapped ? nativeLane : null]);
    if(this.storageDescriptions.has(key))return this.storageDescriptions.get(key);
    const unique=mapped && mapped.index===index && Number.isSafeInteger(index) &&
      mapped.represented_lanes===1 && Number.isFinite(mapped.start_m) && mapped.start_m>0 &&
      mapped.start_m<=(link.data.length_m || link.geometry.length)+1e-7;
    const result={length_m:unique ? Math.min(effectiveLength,mapped.start_m) : effectiveLength,
      source:unique ? 'native_lane_extent_visual_capacity' : 'link_geometry_visual_capacity'};
    this.storageDescriptions.set(key,result);return result;
  }
  intersectionSetback(id,index) {
    const key=JSON.stringify([id,index]);
    if(this.stopMargins.has(key))return this.stopMargins.get(key);
    const link=this.links.get(id);
    if(!link?.eligible || !Number.isSafeInteger(index))return 0;
    const g=link.geometry,u=g.edges.at(-1),end=this.sample(g,1,this.offset(link,index)).position;
    let setback=0;
    // Intersect the incoming lane ray with existing perpendicular road strips.
    // Shared nodes and compatible levels only; nearby unrelated roads do not count.
    for(const other of this.nodeLinks.get(link.data.to_node) || []) {
      if(other===link || !other.eligible || !other.geometry || !this.compatibleLevel(link,other))continue;
      const atStart=other.data.from_node===link.data.to_node;
      const edge=atStart ? other.geometry.edges[0] : other.geometry.edges.at(-1);
      const cross=u.dx*edge.dy-u.dy*edge.dx;
      if(Math.abs(cross)<.25)continue;
      const node=atStart ? other.data.path[0] : other.data.path.at(-1);
      const lateral=(end[0]-node[0])*g.xScale*edge.dy-(end[1]-node[1])*g.yScale*edge.dx;
      // The .82 road stroke is only decorative. The conflict zone must use
      // the full lane width, matching the native corridor conflict margin.
      const lo=this.offset(other,0)-other.width*.5,hi=this.offset(other,other.lanes-1)+other.width*.5;
      setback=Math.max(setback,(lateral-lo)/cross,(lateral-hi)/cross);
    }
    this.stopMargins.set(key,setback);return setback;
  }
  stopBoundary(id,index,setback=2) {
    const link=this.links.get(id);
    if(!link?.eligible || !link.geometry || !Number.isSafeInteger(index) || index<0 || index>=link.lanes ||
       !Number.isFinite(setback) || setback<0)return null;
    const geometric=this.intersectionSetback(id,index),station=link.geometry.length-geometric-setback;
    const point=this.place(id,station,index);
    if(!point)return {available:false,source:'inferred_road_strip_and_visual_setback',explicit:false,
      reason:'insufficient_link_before_conflict',station_m:station,geometric_setback_m:geometric,configured_setback_m:setback};
    const g=link.geometry;
    let edge=g.edges.find((_,i)=>g.distances[i+1]>station) || g.edges.at(-1);
    // Effective metadata has no surveyed stop-bar coordinates. This local
    // cross-section is a documented display margin, never the signal pole.
    return {available:true,source:'inferred_road_strip_and_visual_setback',explicit:false,
      Link_ID:id,lane_index:index,station_m:station,position:point.position,forward:[edge.dx,edge.dy],
      geometric_setback_m:geometric,configured_setback_m:setback};
  }
  place(id,distance,index) {
    const link=this.links.get(id);
    if(!link?.geometry || !Number.isFinite(distance) || distance<0 || distance>link.geometry.length)return null;
    if(index!=null && (!link.eligible || !Number.isSafeInteger(index) || index<0 || index>=link.lanes))return null;
    return this.sample(link.geometry,distance/link.geometry.length,index==null ? 0 : this.offset(link,index));
  }
  bodyGeometry(geometry,center,offset,spacing,length,width,clip) {
    if(!geometry || ![center,length,width].every(Number.isFinite) || length<=0 || width<=0 ||
       center<0 || center>geometry.length)return null;
    const point=this.sample(geometry,center/geometry.length,offset);
    return point ? this.rigidBody(point.position,this.headingAt(geometry,center,length),length,width,geometry) : null;
  }
  interpolateHeading(from,to,fraction) {
    const delta=((to-from+180)%360+360)%360-180;
    return ((from+delta*fraction)%360+360)%360;
  }
  headingAt(geometry,center,length,previous=null,next=null) {
    const edges=geometry.edges,stations=geometry.distances,half=length/2;
    for(let i=1;i<stations.length-1;i++) {
      const radius=Math.min(half,edges[i-1].length/2,edges[i].length/2);
      if(Math.abs(center-stations[i])<=radius)
        return this.interpolateHeading(edges[i-1].heading,edges[i].heading,(center-stations[i]+radius)/(2*radius));
    }
    const firstRadius=Math.min(half,edges[0].length/2),lastRadius=Math.min(half,edges.at(-1).length/2);
    if(previous!=null && center<firstRadius)
      return this.interpolateHeading(previous,edges[0].heading,.5+.5*center/firstRadius);
    if(next!=null && center>geometry.length-lastRadius)
      return this.interpolateHeading(edges.at(-1).heading,next,.5*(center-geometry.length+lastRadius)/lastRadius);
    let index=0;while(index<edges.length-1 && stations[index+1]<=center)index++;
    return ((edges[index].heading%360)+360)%360;
  }
  rigidBody(position,heading,length,width,geometry) {
    if(!this.validPoint(position) || ![heading,length,width].every(Number.isFinite) || length<=0 || width<=0)return null;
    const radians=heading*Math.PI/180,dx=Math.cos(radians)*length/2/geometry.xScale,dy=Math.sin(radians)*length/2/geometry.yScale;
    return {position:[...position],path:[[position[0]-dx,position[1]-dy],[position[0]+dx,position[1]+dy]],
      width_m:width,length_m:length,heading,clipped:false,opacity:1,support:'current_link'};
  }
  observedConnection(a,b) {
    if(!a || !b || a.vehicle!==b.vehicle || a.Agent_ID!==b.Agent_ID || !a.Replay_Journey_Key || a.Replay_Journey_Key!==b.Replay_Journey_Key ||
       a.timestamps[1]!==b.timestamps[0] || a.timestamps[1]<=a.timestamps[0] || b.timestamps[1]<=b.timestamps[0])return false;
    const left=this.links.get(a.Link_ID),right=this.links.get(b.Link_ID);
    const recordedEdge=(record,side)=>{
      const end=side==='end',link=this.links.get(record.Link_ID),point=record.path?.[end ? record.path.length-1 : 0];
      if(!this.occupancy(record) || !link?.geometry || !this.validPoint(point) ||
         record.Boundary_Provenance?.[side]!== (end ? 'left link' : 'entered link') ||
         record.Boundary_Provenance[side+'_relative']!== (end ? 1 : 0))return false;
      // The native link event proves this endpoint independently of the other
      // boundary (e.g. a gateway facility whose location is not a blocking stop).
      const endpoint=this.sample(link.geometry,end ? 1 : 0,0)?.position;
      if(!endpoint)return false;
      return Math.hypot((endpoint[0]-point[0])*link.geometry.xScale,(endpoint[1]-point[1])*link.geometry.yScale)<=.25;
    };
    if(!left?.geometry || !right?.geometry || left.data.to_node==null || left.data.to_node!==right.data.from_node ||
       !this.compatibleLevel(left,right) || !(this.compatiblePath(left,a.path) || recordedEdge(a,'end')) ||
       !(this.compatiblePath(right,b.path) || recordedEdge(b,'start')))return false;
    const end=left.geometry.points.at(-1),start=right.geometry.points[0];
    if(Math.hypot(end[0]-start[0],end[1]-start[1])>1e-5)return false;
    const targets=Number.isSafeInteger(a.Visual_Lane_Index) ? this.targets(left,a.Visual_Lane_Index) : left.data.allowed_to_links;
    return Array.isArray(targets) && targets.includes(b.Link_ID);
  }
  vehicleBody(marker,neighbors={},length=null,width=null) {
    if(length==null || width==null) {
      const dimensions=SimZ1VehicleCatalog.resolve(marker).dimensions;
      if(!dimensions)return null;
      length=length ?? dimensions.length_m;width=width ?? dimensions.width_m;
    }
    const facility=marker.Visual_Facility_Footprint_Projection ? null : this.nativeFacilityPose(marker);
    if(facility) {
      const geometry=this.links.get(marker.Link_ID).geometry;
      const body=this.rigidBody(facility.position,this.headingAt(geometry,facility.station_m,length),length,width,geometry);
      if(body)body.support='native_facility_center_estimated_orientation';
      return body;
    }
    const link=this.links.get(marker.Link_ID),fraction=marker.Visual_Motion_Fraction;
    const compatible=this.compatiblePath(link,marker.path),geometry=compatible ? link.geometry : this.geometry(marker.path);
    if(!geometry || !Number.isFinite(fraction))return this.centerBody(marker.path,fraction,length,width,marker.Link_ID);
    const center=marker.Visual_Queue_Center_Meters ?? marker.Visual_Native_Queue_Station_Meters ?? fraction*geometry.length;
    if(!Number.isFinite(center) || center<0 || center>geometry.length)return null;
    // A queued body must remain aligned with its current lane, even at a short
    // link's end. Turning/averaging endpoints during a hold puts it across lanes.
    // Spacing can already adjust a moving approach before its observed hold.
    // Only an explicit moving flag permits the recorded transition in that
    // case; older callers with a queue centre retain their held orientation.
    const queued=marker.Waiting===true || marker.Visual_Queue_Holding===true ||
      marker.Visual_Queue_Holding!==false && Number.isFinite(marker.Visual_Queue_Center_Meters);
    const position=[...marker.position],radius=Math.min(length/2,geometry.length/2);
    const endpoint=(record,end)=>{
      const road=this.links.get(record.Link_ID),index=record.Visual_Lane_Index;
      return this.sample(road.geometry,end,road.eligible && Number.isSafeInteger(index) ? this.offset(road,index) : 0)?.position;
    };
    const canJoin=(a,b)=>{
      if(queued || !this.observedConnection(a,b))return false;
      const left=this.links.get(a.Link_ID),right=this.links.get(b.Link_ID);
      if([a,b].some(row=>this.links.get(row.Link_ID).lanes>1 && !Number.isSafeInteger(row.Visual_Lane_Index)))return false;
      const u=left.geometry.edges.at(-1),v=right.geometry.edges[0],dot=u.dx*v.dx+u.dy*v.dy;
      if(dot<-.98)return false; // A U-turn needs a path that the node alone cannot supply.
      const start=endpoint(a,1),end=endpoint(b,0);
      if(!start || !end)return false;
      // On straight continuations a mean between different lanes is not a lane.
      return dot<.98 || Math.hypot((start[0]-end[0])*geometry.xScale,(start[1]-end[1])*geometry.yScale)<=.25;
    };
    const previous=canJoin(neighbors.previous,marker) ? neighbors.previous : null;
    const next=canJoin(marker,neighbors.next) ? neighbors.next : null;
    const before=previous ? this.links.get(previous.Link_ID).geometry.edges.at(-1).heading : null;
    const after=next ? this.links.get(next.Link_ID).geometry.edges[0].heading : null;
    // Only a recorded, contiguous and permitted transition supports a shared
    // visual joint. This estimated pose changes neither lanes nor Motion_Plan.
    const join=(neighbor,atStart,weight)=>{
      // A serial native queue bounds the centre on this link. The observed
      // transition may inform heading, but cannot move that centre outside it.
      if(marker.Visual_Native_Queue_Extent?.available)return;
      const own=endpoint(marker,atStart ? 0 : 1),other=endpoint(neighbor,atStart ? 1 : 0);
      if(own && other)for(let i=0;i<2;i++)position[i]+=(other[i]-own[i])*.5*weight;
    };
    if(previous && center<radius)join(previous,true,1-center/radius);
    if(next && center>geometry.length-radius)join(next,false,1-(geometry.length-center)/radius);
    const body=this.rigidBody(position,this.headingAt(geometry,center,length,before,after),length,width,geometry);
    if(body)body.support=previous || next ? 'observed_transition_estimated_pose' : 'current_link';
    return body;
  }
  body(id,center,index,length=4.5,width=1.8,clip=false) {
    const link=this.links.get(id);
    if(!link?.geometry || index!=null && (!link.eligible || !Number.isSafeInteger(index) || index<0 || index>=link.lanes))return null;
    const spacing=index!=null && link.lanes+link.opposing>1 ? link.width*this.lateralScale(link) : null;
    return this.bodyGeometry(link.geometry,center,index==null ? 0 : this.offset(link,index),spacing,length,width,clip);
  }
  centerBody(path,fraction,length=4.5,width=1.8,id=null) {
    if(!Number.isFinite(fraction))return null;
    const link=this.links.get(id);
    const geometry=this.compatiblePath(link,path) ? link.geometry : this.geometry(path);
    if(!geometry && link?.geometry && Array.isArray(path) && path.length>=2 && path.every(p=>this.validPoint(p)) &&
       path.every(p=>p[0]===path[0][0] && p[1]===path[0][1])) {
      // A recorded fixed point has a position even though its path has no length.
      // Estimate orientation only when it coincides with a known link endpoint.
      for(const end of [0,1]) {
        const point=this.sample(link.geometry,end,0)?.position;
        if(point && Math.hypot((point[0]-path[0][0])*link.geometry.xScale,(point[1]-path[0][1])*link.geometry.yScale)<=.25)
          return this.rigidBody(path[0],this.headingAt(link.geometry,end*link.geometry.length,length),length,width,link.geometry);
      }
    }
    return geometry && Number.isFinite(fraction) ?
      this.bodyGeometry(geometry,Math.max(0,Math.min(1,fraction))*geometry.length,0,null,length,width,true) : null;
  }
  roads() {
    return this.roadCache;
  }
  buildLabelCandidates() {
    const groups=new Map(),result=[];
    for(const link of this.links.values()) {
      const rawName=link.data.osm_tags?.name,name=typeof rawName==='string' ? rawName.trim() : null;
      if(!name || !link.geometry)continue;
      if(!groups.has(name))groups.set(name,[]);
      groups.get(name).push(link);
    }
    for(const [name,links] of [...groups].sort((a,b)=>a[0].localeCompare(b[0]))) {
      const endpoints=links.flatMap(link=>[0,1].map(end=>({link,end,p:link.geometry.points.at(end ? -1 : 0)})));
      const extent=axis=>Math.max(...endpoints.map(e=>e.p[axis]))-Math.min(...endpoints.map(e=>e.p[axis]));
      const axis=extent(0)>=extent(1) ? 0 : 1;
      endpoints.sort((a,b)=>a.p[axis]-b.p[axis] || a.link.id.localeCompare(b.link.id));
      const first=endpoints[0],last=endpoints.at(-1);
      const long=Math.hypot(last.p[0]-first.p[0],last.p[1]-first.p[1])>=250;
      const midpoint=(first.p[axis]+last.p[axis])/2;
      const distance=link=>Math.abs((link.geometry.points[0][axis]+link.geometry.points.at(-1)[axis])/2-midpoint);
      const middle={link:[...links].sort((a,b)=>(long ? distance(a)-distance(b) : 0) ||
        b.geometry.length-a.geometry.length || a.id.localeCompare(b.id))[0],end:.5};
      const anchors=(long ? [first,last,middle] : [middle]).map(({link,end},rank)=>({link,
        fraction:end===.5 ? .5 : end ? 1-Math.min(25/link.geometry.length,.5) : Math.min(25/link.geometry.length,.5),
        fallback:long && rank===2}));
      // Keep sparse endpoint labels, but a rejected centre is not the last
      // chance. Try nearby positions along actual named geometry (including
      // inside links), with deterministic ordering and reverse-link deduping.
      for(const link of [...links].sort((a,b)=>distance(a)-distance(b) || a.id.localeCompare(b.id)))
        for(const fraction of [.5,.25,.75,.125,.375,.625,.875])anchors.push({link,fraction,fallback:true});
      const seen=new Set();
      for(const [rank,{link,fraction,fallback}] of anchors.entries()) {
        const g=link.geometry;
        const point=this.sample(g,fraction,0),near=this.sample(g,Math.min(1,fraction+Math.min(5/g.length,.1)),0);
        const key=point?.position.map(value=>value.toFixed(11)).join(',');
        if(!point || !near || seen.has(key))continue;
        seen.add(key);
        const edge=this.sample(g,fraction,(link.lanes+link.opposing)*link.width/2);
        result.push({name,position:point.position,tangent:near.position,edge:edge?.position,
          Link_ID:link.id,rank,fallback,kind:'road'});
      }
    }
    for(const row of this.options.landmarks || [])if(typeof row.name==='string' && this.validPoint(row.position) && row.source==='recorded_osm_node')
      result.push({...row,rank:0,kind:'landmark'});
    return result;
  }
  labels(viewState,project,width,height,contains=()=>true,allowed=null) {
    if(!Number.isFinite(viewState?.zoom) || viewState.zoom<15 || typeof project!=='function' || !(width>0 && height>0))return [];
    const result=[],boxes=[],names=new Map();let landmarks=0;
    for(const row of this.labelCandidates || []) {
      if(!contains(row.position) || row.kind==='road' && allowed && !allowed.has(row.Link_ID))continue;
      if(row.kind==='landmark' && (viewState.zoom<16 || landmarks>=6))continue;
      const key=row.kind+'\0'+row.name,limit=row.kind==='road' && viewState.zoom>=16.7 ? 2 : 1;
      if((names.get(key) || 0)>=limit)continue;
      if(row.fallback && names.has(key))continue; // Alternatives rescue a missing name, never add density.
      const p=project(row.position),q=row.tangent ? project(row.tangent) : null;
      if(!p || !Number.isFinite(p[0]) || !Number.isFinite(p[1]) || q && (!Number.isFinite(q[0]) || !Number.isFinite(q[1])))continue;
      let angle=q ? Math.atan2(p[1]-q[1],q[0]-p[0])*180/Math.PI : 0;
      if(angle>90)angle-=180;if(angle< -90)angle+=180;
      const radians=angle*Math.PI/180,textWidth=row.name.length*8.5+12;
      const edge=row.edge ? project(row.edge) : null;
      const margin=edge && Number.isFinite(edge[0]) && Number.isFinite(edge[1]) ? Math.hypot(edge[0]-p[0],edge[1]-p[1]) : 0;
      // Move road text outside its road strip, in CSS pixels. Collision tests
      // must use that same offset; labels stay non-pickable and have no fill.
      const offset=row.kind==='road' ? margin+16 : 0;
      const pixelOffset=[-Math.sin(radians)*offset,-Math.cos(radians)*offset];
      const center=[p[0]+pixelOffset[0],p[1]+pixelOffset[1]];
      const rx=(Math.abs(Math.cos(radians))*textWidth+Math.abs(Math.sin(radians))*18)/2+6;
      const ry=(Math.abs(Math.sin(radians))*textWidth+Math.abs(Math.cos(radians))*18)/2+6;
      const box=[center[0]-rx,center[1]-ry,center[0]+rx,center[1]+ry];
      if(box[0]<8 || box[1]<8 || box[2]>width-8 || box[3]>height-8 ||
        boxes.some(b=>box[0]<b[2] && box[2]>b[0] && box[1]<b[3] && box[3]>b[1]))continue;
      boxes.push(box);result.push({...row,angle,pixelOffset});names.set(key,(names.get(key) || 0)+1);
      if(row.kind==='landmark')landmarks++;
      if(result.length>=60)break;
    }
    return result;
  }
}
