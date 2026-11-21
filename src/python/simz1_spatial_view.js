/* View-only Polygon clipping. Source paths, native times and OD records stay intact. */
class SimZ1SpatialView {
  constructor(spatial,identity) {
    this.balanced=spatial?.schema_version===2 && spatial.mode==='balanced-gateway-v1';
    if(!spatial || !(this.balanced || spatial.schema_version===1 && spatial.mode==='gateway-od') || spatial.validated!==true ||
       !identity || typeof identity.run_id!=='string' || !identity.run_id.trim() ||
       !Number.isSafeInteger(identity.iteration) || identity.iteration<0 ||
       typeof identity.run_manifest_sha256!=='string' || !/^[a-f\d]{64}$/i.test(identity.run_manifest_sha256) ||
       ['run_id','iteration','run_manifest_sha256'].some(key=>spatial.identity?.[key]!==identity[key]))
      throw new Error('Dominio espacial sin identidad validada');
    const polygon=spatial.boundary;
    if(polygon?.type!=='Polygon' || !Array.isArray(polygon.coordinates) || !polygon.coordinates.length)
      throw new Error('Limite espacial Polygon ausente');
    this.rings=polygon.coordinates.map(ring=>{
      if(!Array.isArray(ring) || ring.length<4 || ring.some(p=>!SimZ1SpatialView.point(p)) ||
         !this.same(ring[0],ring[ring.length-1]) || new Set(ring.map(p=>p.slice(0,2).join(','))).size<3)
        throw new Error('Anillo espacial invalido');
      const origin=ring[0],area=ring.slice(1).reduce((sum,p,i)=>sum+
        (ring[i][0]-origin[0])*(p[1]-origin[1])-(p[0]-origin[0])*(ring[i][1]-origin[1]),0);
      if(Math.abs(area)<=1e-20)throw new Error('Anillo espacial degenerado');
      return ring.map(p=>p.slice(0,2));
    });
    if(!Array.isArray(spatial.allowed_links) || !spatial.allowed_links.length ||
       spatial.allowed_links.some(id=>typeof id!=='string' || !id))throw new Error('Enlaces espaciales ausentes');
    if(this.balanced && (spatial.postprocessor_contract_version!=='balanced-replay-contract-v1' ||
       spatial.visual_scope!=='full_native_network_preserving_anchors_and_services' ||
       !Array.isArray(spatial.visual_link_ids) || !spatial.visual_link_ids.length ||
       spatial.visual_link_ids.some(id=>typeof id!=='string' || !id) ||
       !spatial.allowed_links.every(id=>spatial.visual_link_ids.includes(id)) ||
       ![86400,108000].includes(spatial.observation_end_seconds)))throw new Error('Dominio nativo balanceado sin respaldo');
    this.allowed=new Set(this.balanced ? spatial.visual_link_ids : spatial.allowed_links);this.spatial=spatial;
    this.privateAllowed=new Set(spatial.allowed_links);
  }
  static point(p) {return Array.isArray(p) && p.length>=2 && p.slice(0,2).every(Number.isFinite) && Math.abs(p[0])<=180 && Math.abs(p[1])<=90;}
  same(a,b) {return Math.abs(a[0]-b[0])<1e-11 && Math.abs(a[1]-b[1])<1e-11;}
  cross(a,b) {return a[0]*b[1]-a[1]*b[0];}
  onSegment(p,a,b) {
    const d=[b[0]-a[0],b[1]-a[1]],q=[p[0]-a[0],p[1]-a[1]],length=Math.hypot(...d);
    return length>0 && Math.abs(this.cross(d,q))<=1e-11*length &&
      q[0]*d[0]+q[1]*d[1]>=-1e-11*length && q[0]*d[0]+q[1]*d[1]<=length*length+1e-11*length;
  }
  ringContains(p,ring) {
    let inside=false;
    for(let i=1;i<ring.length;i++) {
      const a=ring[i-1],b=ring[i];
      if(this.onSegment(p,a,b))return 0; // boundary
      if((a[1]>p[1])!==(b[1]>p[1]) && p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;
    }
    return inside ? 1 : -1;
  }
  contains(p) {
    if(this.balanced)return SimZ1SpatialView.point(p);
    return SimZ1SpatialView.point(p) && this.ringContains(p,this.rings[0])>=0 &&
      this.rings.slice(1).every(ring=>this.ringContains(p,ring)<=0);
  }
  clipPath(path) {
    if(!Array.isArray(path) || path.length<2 || path.some(p=>!SimZ1SpatialView.point(p)))return [];
    if(this.balanced)return [path]; // Native modeled anchors/services remain visible.
    const pieces=[];
    for(let i=1;i<path.length;i++) {
      const a=path[i-1],b=path[i],d=[b[0]-a[0],b[1]-a[1]],norm=d[0]*d[0]+d[1]*d[1];
      if(norm===0)continue;
      const cuts=[0,1];
      for(const ring of this.rings)for(let j=1;j<ring.length;j++) {
        const c=ring[j-1],e=[ring[j][0]-c[0],ring[j][1]-c[1]],q=[c[0]-a[0],c[1]-a[1]],den=this.cross(d,e);
        if(Math.abs(den)>1e-20) {
          const t=this.cross(q,e)/den,u=this.cross(q,d)/den;
          if(t>0 && t<1 && u>=0 && u<=1)cuts.push(t);
        } else if(Math.abs(this.cross(d,q))<=1e-11*Math.sqrt(norm)) {
          for(const p of [c,ring[j]]) {const t=((p[0]-a[0])*d[0]+(p[1]-a[1])*d[1])/norm;if(t>0 && t<1)cuts.push(t);}
        }
      }
      cuts.sort((x,y)=>x-y);
      const at=t=>[a[0]+t*d[0],a[1]+t*d[1]];
      for(let j=1;j<cuts.length;j++) {
        if(cuts[j]-cuts[j-1]<1e-12 || !this.contains(at((cuts[j]+cuts[j-1])/2)))continue;
        const start=at(cuts[j-1]),end=at(cuts[j]),last=pieces[pieces.length-1];
        // Never reconnect across a hole or an excursion outside the polygon.
        if(last && this.same(last[last.length-1],start))last.push(end);else pieces.push([start,end]);
      }
    }
    return pieces;
  }
  paths(rows,key='path') {
    return rows.flatMap(row=>this.clipPath(row[key]).map(path=>({...row,[key]:path})));
  }
  positions(rows) {return rows.filter(row=>this.contains(row.position));}
  clearance(path) {
    // Conservative metres in this local Z1 polygon; minimum segment separation
    // bounds the full body's width, including bends and nearby hole boundaries.
    if(!path.every(p=>this.contains(p)))return 0;
    if(this.balanced)return Infinity; // No presentation-only polygon wall in the native network.
    const latitude=path.reduce((sum,p)=>sum+p[1],0)/path.length*Math.PI/180;
    const sx=111000*Math.cos(latitude),sy=110500;
    const xy=p=>[p[0]*sx,p[1]*sy];
    const distance=(p,a,b)=>{
      const d=[b[0]-a[0],b[1]-a[1]],n=d[0]*d[0]+d[1]*d[1];
      const t=n ? Math.max(0,Math.min(1,((p[0]-a[0])*d[0]+(p[1]-a[1])*d[1])/n)) : 0;
      return Math.hypot(p[0]-a[0]-t*d[0],p[1]-a[1]-t*d[1]);
    };
    let minimum=Infinity;
    for(let i=1;i<path.length;i++)for(const ring of this.rings)for(let j=1;j<ring.length;j++) {
      const a=xy(path[i-1]),b=xy(path[i]),c=xy(ring[j-1]),d=xy(ring[j]);
      minimum=Math.min(minimum,distance(a,c,d),distance(b,c,d),distance(c,a,b),distance(d,a,b));
    }
    return minimum*.99;
  }
  markerVisible(row) {
    // An estimated lane/queue offset cannot change the native domain. The
    // unshifted source centre governs membership when explicitly supplied;
    // older callers without it preserve their supported-centre behaviour.
    return Boolean(row && this.allowed.has(row.Link_ID) &&
      this.contains(row.Visual_Native_Center_Position ?? row.position));
  }
  markers(rows) {
    // Keep the complete rigid footprint; spatial membership never cuts a body.
    return rows.filter(row=>this.markerVisible(row));
  }
  validateTrip(trip) {
    if(trip?.Transit) {
      const transit=SimZ1ContinuousLoader.transitTrip(trip);
      if(!transit.route_links.every(link=>this.allowed.has(link)))throw new Error('Ruta publica fuera del dominio validado');
      return transit;
    }
    if(trip?.Freight) {
      const f=trip.Freight;
      if(!this.balanced || f.vehicle_id!==trip.Person_ID || trip.Trip_Index!==1 ||
         trip.Trip_ID!==f.vehicle_id+':trip:0001' || typeof f.route_id!=='string' || !f.route_id ||
         !Number.isFinite(f.planned_departure) || Math.abs(trip.Departure-f.planned_departure)>1.01 ||
         !/^[a-f\d]{64}$/i.test(f.roster_source?.sha256 || '') ||
         !Array.isArray(f.route_link_ids) || !f.route_link_ids.length || !f.route_link_ids.every(id=>this.allowed.has(id)))
        throw new Error('Carga sin identidad/ruta nativa validada');
      return f;
    }
    if(this.balanced)return this.validateBalancedTrip(trip);
    const od=trip?.OD,external=new Set(['external-external','external-internal','internal-external','internal-internal']);
    const fields=['od_type','origin_link','destination_link','origin_gateway','destination_gateway','origin_zone','destination_zone','scope','door_to_door_seconds','metadata_source'];
    const classes={'internal-internal':'INTERNAL_INTERNAL','internal-external':'INTERNAL_EXTERNAL',
      'external-internal':'EXTERNAL_INTERNAL','external-external':'EXTERNAL_EXTERNAL_THROUGH'};
    if(od && Object.prototype.hasOwnProperty.call(od,'od_class'))fields.push('od_class');
    if(!od || !external.has(od.od_type) || od.scope!=='observed_z1_only' || od.door_to_door_seconds!==null ||
       (fields.includes('od_class') && od.od_class!==classes[od.od_type]) ||
       (this.spatial.od_contract==='simz1-four-od-v2' && !fields.includes('od_class')) ||
       Object.keys(od).length!==fields.length || fields.some(key=>!Object.prototype.hasOwnProperty.call(od,key)) ||
       od.metadata_source!=='synthetic_gateway_od' || !this.allowed.has(od.origin_link) || !this.allowed.has(od.destination_link) ||
       od.origin_link===od.destination_link || !Number.isFinite(trip.Departure))
      throw new Error('Viaje sin OD espacial validado');
    for(const [side,index] of [['origin',0],['destination',1]]) {
      const outside=od.od_type.split('-')[index]==='external',gateway=od[side+'_gateway'],zone=od[side+'_zone'];
      const role=side==='origin' ? 'entry' : 'exit',link=od[side+'_link'];
      if(outside ? gateway!==link || !Object.prototype.hasOwnProperty.call(this.spatial[role+'_gateways'] || {},link) ||
          zone!=='synthetic-exterior-'+role+':'+link : gateway!==null || zone!==null || !this.spatial.internal_links?.includes(link))
        throw new Error('Zona/puerta OD incompatible');
    }
    return od;
  }
  validateBalancedTrip(trip) {
    const od=trip?.OD,classes={'internal-internal':'INTERNAL_INTERNAL','internal-external':'INTERNAL_EXTERNAL',
      'external-internal':'EXTERNAL_INTERNAL','external-external':'EXTERNAL_EXTERNAL_THROUGH'};
    const fields=['od_type','od_class','origin_link','destination_link','origin_gateway','destination_gateway',
      'origin_zone','destination_zone','scope','door_to_door_seconds','metadata_source','route_link_ids',
      'body_length_m','minimum_gap_m','entry_crossing_link','exit_crossing_link','origin_observation_link','destination_observation_link'];
    if(!od || Object.keys(od).length!==fields.length || fields.some(k=>!Object.hasOwn(od,k)) ||
       !classes[od.od_type] || od.od_class!==classes[od.od_type] ||
       od.scope!=='observed_z1_and_declared_anchors_only' || od.metadata_source!=='simz1-private-gateway-trip-v1' ||
       od.door_to_door_seconds!==null || !Number.isFinite(od.body_length_m) || od.body_length_m<=0 || od.minimum_gap_m!==.1 ||
       !Number.isFinite(trip.Departure) || od.origin_link===od.destination_link ||
       !Array.isArray(od.route_link_ids) || od.route_link_ids[0]!==od.origin_link || od.route_link_ids.at(-1)!==od.destination_link ||
       !od.route_link_ids.every(id=>this.privateAllowed.has(id)))throw new Error('OD balanceado incompatible');
    for(const [side,role,index] of [['origin','entry',0],['destination','exit',1]]) {
      const row=this.spatial[role+'_gateways']?.[od[side+'_link']],outside=od.od_type.split('-')[index]==='external';
      if(outside ? !row || od[side+'_gateway']!==od[side+'_link'] || od[side+'_zone']!==row.id ||
          od[role+'_crossing_link']!==row.crossing_link || od[side+'_observation_link']!==row.observation_link :
          !this.spatial.internal_links?.includes(od[side+'_link']) ||
          [od[side+'_gateway'],od[side+'_zone'],od[role+'_crossing_link'],od[side+'_observation_link']].some(v=>v!==null))
        throw new Error('Zona/puerta balanceada incompatible');
    }
    return od;
  }
  tripText(trip,time,format) {
    if(trip?.Transit) {
      const t=this.validateTrip(trip);
      return '\nServicio: '+(t.service_id ?? t.line_id)+' | Salida: '+t.departure_id+
        '\nDominio: '+t.domain_scope+'; sin tiempo exterior inferido';
    }
    if(trip?.Freight) {
      const f=this.validateTrip(trip);
      return '\nCarga: '+f.route_id+' | Programada: '+format(f.planned_departure)+
        '\nLlegada nativa: '+(Number.isFinite(trip.Arrival) ? format(trip.Arrival) : 'N/D')+
        '\nTolerancia y despeje corporal: consultar informe de carga de esta iteracion.';
    }
    const limit=this.balanced ? this.spatial.observation_end_seconds : 86400;
    const od=this.validateTrip(trip),censored=trip.Status==='censored' || trip.Censored_At_Day_End || trip.Arrival>limit;
    const native=!!od.od_class,start=native ? trip.System_Entry : trip.Departure,end=native ? trip.System_Exit : trip.Arrival;
    const complete=Number.isFinite(start) && Number.isFinite(end) && end>=start && end<=limit &&
      (native || trip.Status==='completed' && !censored);
    const observedEnd=Math.min(time,limit,...[end,trip.Abort,trip.Observation_End].filter(Number.isFinite));
    const elapsed=Number.isFinite(start) ? format(Math.max(0,observedEnd-start)) : 'N/D (sin entrada observada)';
    const state=censored ? 'censurado' : trip.Status==='aborted' || Number.isFinite(trip.Abort) ? 'abortado' : 'observado';
    return '\nOD global: '+(od.origin_zone ?? 'interior Z1')+' -> '+(od.destination_zone ?? 'interior Z1')+
      '\nOrigen efectivo: '+od.origin_link+(od.origin_gateway ? ' | puerta '+od.origin_gateway : '')+
      '\nDestino efectivo previsto: '+od.destination_link+(od.destination_gateway ? ' | puerta '+od.destination_gateway : '')+
      '\nTiempo transcurrido en tramo modelado Z1: '+elapsed+' ('+state+'; tiempo observado)'+
      '\nTiempo completo en tramo modelado Z1: '+(complete ? format(end-start) : 'N/D (sin salida observada en la jornada)')+
      '\nTiempo puerta a puerta: N/D | OD sintetico por puertas; sin trayecto exterior observado';
  }
}
if(typeof module!=='undefined' && module.exports)module.exports=SimZ1SpatialView;
