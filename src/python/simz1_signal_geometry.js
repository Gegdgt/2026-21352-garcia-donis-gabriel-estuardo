/* SimZ1 presentation only: no changes to native groups, lanes or clocks.
 * deck.gl 9.1.14 SimpleMeshLayer, instanced metre offsets in LNGLAT.
 * World X=east, Y=north, Z=up. Mesh front=+Y, right=+X, pole=+Z.
 * Incoming terminal tangent u points downstream; the face normal is -u.
 * Column-major transform maps local right/front/up into ENU, independently
 * of camera bearing/pitch. Deck applies the view transform exactly once.
 */
class SimZ1SignalGeometry {
  static version='simz1-single-head-signals-v3';
  // Explicit visual assumptions, not surveyed pole/head measurements.
  static dimensions=Object.freeze({pole_height_m:1.5,head_bottom_m:1.2,head_top_m:4.2,
    head_width_m:1.2,head_depth_m:.55,lamp_radius_m:.34});
  static policy=Object.freeze({detail_on:16.6,detail_off:16.2,
    overview_min_pixels:18,overview_max_pixels:22,detail_min_pixels:24,detail_max_pixels:34,
    visual_scale:2,roadside_clearance_m:.5,terminal_setback_m:3});
  static colors=Object.freeze({RED:[255,55,55,255],YELLOW:[255,210,30,255],GREEN:[40,235,105,255],
    OFF:[54,62,70,255],UNKNOWN:[255,255,255,255]});
  static validPosition(p) {
    return Array.isArray(p) && p.length>=2 && p.slice(0,2).every(Number.isFinite) &&
      Math.abs(p[0])<=180 && Math.abs(p[1])<85 && (p.length<3 || Number.isFinite(p[2]));
  }
  static terminalTangent(path) {
    if(!Array.isArray(path) || path.length<2 || !path.every(this.validPosition))return null;
    const end=path.at(-1),scale=Math.cos(end[1]*Math.PI/180);
    for(let i=path.length-2;i>=0;i--) {
      const dx=(end[0]-path[i][0])*scale,dy=end[1]-path[i][1],length=Math.hypot(dx,dy);
      if(length>1e-12)return [dx/length,dy/length];
    }
    return null;
  }
  static transform(front,z=0) {
    const [x,y]=front;
    return [y,-x,0,0, x,y,0,0, 0,0,1,0, 0,0,z,1];
  }
  static anchor(record,link,renderer) {
    const g=link?.geometry,u=g?.edges.at(-1);
    if(!u || !this.terminalTangent(link.data.path) || link.data.geometry_source?.includes('invalid_geometry'))return null;
    // The old export's 18 m / 8 m offsets were not pole observations. Use only
    // this directed link's terminal segment and the SAME displayed lane border.
    // Never snap to a nearest road, a current OSM map, or an adjacent link.
    const setback=Math.min(this.policy.terminal_setback_m,u.length*.35);
    const fraction=(g.length-setback)/g.length;
    const border=link.eligible ? renderer.offset(link,link.lanes-1)+link.width*.41 : link.width*.41;
    const offset=border+this.policy.roadside_clearance_m;
    const point=renderer.sample(g,fraction,offset);
    if(!point)return null;
    const anchor=[...point.position,Number.isFinite(record.position?.[2]) ? record.position[2] : 0];
    const shift=this.validPosition(record.position) ? Math.hypot((anchor[0]-record.position[0])*g.xScale,
      (anchor[1]-record.position[1])*g.yScale) : null;
    return {anchor,source:'effective_terminal_lane_border',setback_m:setback,lateral_offset_m:offset,
      displacement_m:shift,corrected:shift===null || shift>.05};
  }
  constructor(records,laneRenderer,spatial=null) {
    this.records=[];this.oriented=[];this.unoriented=[];this.lamps=[];this.issues=[];
    this.detail=null;this.viewKey=null;this.revision=0;this.viewBuilds=0;
    this.frame=new Map();this.clusters=new Map();
    for(const record of records) {
      // A missing direction remains explicit. Never infer it from the old
      // 0/90 icon angle, screen coordinates, a nearby road or today's map.
      const link=laneRenderer?.links.get(record.Link_ID);
      const placement=this.constructor.anchor(record,link,laneRenderer);
      const tangent=placement ? this.constructor.terminalTangent(link?.data.path) : null;
      const anchor=placement?.anchor || (this.constructor.validPosition(record.position) ? [...record.position] : null);
      const valid=Boolean(anchor);
      const reason=!valid ? 'invalid_anchor' : !tangent ? 'directed_link_geometry_unavailable' : null;
      // Domain filtering follows the corrected anchor, not the displaced legacy one.
      if(spatial && (!spatial.allowed.has(record.Link_ID) || !anchor || !spatial.contains(anchor)))continue;
      const front=tangent ? tangent.map(value=>-value) : null;
      const row={...record,Signal_Geometry:{version:this.constructor.version,
        source:front ? 'directed_link_terminal_tangent' : null,reason,
        approach_unit_enu:tangent,front_unit_enu:front,up_unit_enu:[0,0,1],
        incoming_bearing_deg:tangent ? (Math.atan2(tangent[0],tangent[1])*180/Math.PI+360)%360 : null,
        transform:front ? this.constructor.transform(front) : null,
        anchor,source_anchor:record.position ? [...record.position] : null,placement,
        // Distinct native nodes stay distinct, even at the same screen pixel.
        intersection_key:link?.data.to_node!=null ? 'node:'+link.data.to_node : 'link:'+record.Link_ID}};
      this.records.push(row);
      if(reason)this.issues.push({system_id:record.system_id,group_id:record.group_id,signal_id:record.signal_id,Link_ID:record.Link_ID,reason});
      if(!valid)continue;
      if(!front){this.unoriented.push(row);continue;}
      this.oriented.push(row);
      const cluster=row.Signal_Geometry.intersection_key;
      if(!this.clusters.has(cluster))this.clusters.set(cluster,[]);
      this.clusters.get(cluster).push(row);
      // Exactly one vertical head per native signal. The previous horizontal
      // top repeater made a second head/L silhouette; never duplicate it for
      // a camera pose. From directly overhead the real head is seen edge-on.
      for(const [lamp,z] of [[0,3.65],[1,2.7],[2,1.75]]) {
        const m=this.constructor.transform(front,z),d=this.constructor.dimensions;
        m[12]=front[0]*(d.head_depth_m/2+.015);m[13]=front[1]*(d.head_depth_m/2+.015);
        this.lamps.push({...row,Signal_Lamp:lamp,Signal_Surface:'front',Signal_Lamp_Transform:m});
      }
    }
    // A representative is an actual signal with its own native state, never a
    // synthetic averaged phase. Prefer the widest recorded access, then stable ID.
    const rank=row=>laneRenderer.links.get(row.Link_ID)?.lanes || 0;
    for(const members of this.clusters.values())members.sort((a,b)=>rank(b)-rank(a) ||
      JSON.stringify([a.Link_ID,a.system_id,a.group_id,a.signal_id]).localeCompare(JSON.stringify([b.Link_ID,b.system_id,b.group_id,b.signal_id])));
    this.overview=Array.from(this.clusters.values(),members=>members[0]);
    const selected=new Set(this.overview.map(row=>row.Signal_Geometry));
    this.overviewLamps=this.lamps.filter(row=>selected.has(row.Signal_Geometry));
  }
  static mesh(faces) {
    const positions=[],normals=[],colors=[];
    for(const {points,normal,color} of faces)for(let i=1;i<points.length-1;i++)for(const point of [points[0],points[i],points[i+1]]) {
      positions.push(...point);normals.push(...normal);colors.push(...color.map(value=>value/255));
    }
    return {attributes:{POSITION:{size:3,value:new Float32Array(positions)},
      NORMAL:{size:3,value:new Float32Array(normals)},COLOR_0:{size:3,value:new Float32Array(colors)}}};
  }
  static box(x,y,bottom,top) {
    return [
      {normal:[0,1,0],color:[21,25,31],points:[[-x,y,bottom],[-x,y,top],[x,y,top],[x,y,bottom]]},
      {normal:[0,-1,0],color:[77,87,97],points:[[x,-y,bottom],[x,-y,top],[-x,-y,top],[-x,-y,bottom]]},
      {normal:[1,0,0],color:[108,119,130],points:[[x,y,bottom],[x,y,top],[x,-y,top],[x,-y,bottom]]},
      {normal:[-1,0,0],color:[64,74,84],points:[[-x,-y,bottom],[-x,-y,top],[-x,y,top],[-x,y,bottom]]},
      {normal:[0,0,1],color:[145,155,165],points:[[-x,-y,top],[x,-y,top],[x,y,top],[-x,y,top]]},
      {normal:[0,0,-1],color:[54,62,70],points:[[-x,y,bottom],[x,y,bottom],[x,-y,bottom],[-x,-y,bottom]]}
    ];
  }
  static meshes() {
    if(this.cachedMeshes)return this.cachedMeshes;
    const d=this.dimensions,pole=this.box(.09,.09,0,d.pole_height_m).map(face=>({...face,color:[173,181,189]})),points=[];
    // Front-only fan: +Y normal, 20 triangles; the opaque housing hides its
    // reverse side. Separate planes prevent coplanar flicker with the face.
    points.push([0,0,0]);
    for(let i=0;i<=20;i++) {
      const a=-i*Math.PI/10;
      points.push([d.lamp_radius_m*Math.cos(a),0,d.lamp_radius_m*Math.sin(a)]);
    }
    this.cachedMeshes={body:this.mesh([...pole,...this.box(d.head_width_m/2,d.head_depth_m/2,d.head_bottom_m,d.head_top_m)]),
      pole:this.mesh(pole),lamp:this.mesh([{points,normal:[0,1,0],color:[255,255,255]}])};
    return this.cachedMeshes;
  }
  static lampColor(row,state) {
    const name=['RED','YELLOW','GREEN'][row.Signal_Lamp];
    return state===name || state==='REDYELLOW' && row.Signal_Lamp<2 ? this.colors[name] : this.colors.OFF;
  }
  static scaled(matrix,scale) {return matrix.map((value,i)=>i===15 ? value : value*scale);}
  static corners(row,scale=1) {
    const g=row.Signal_Geometry,m=g.transform || this.transform([0,1]),p=g.anchor,d=this.dimensions;
    const metres=6371008.8*Math.PI/180,sx=metres*Math.cos(p[1]*Math.PI/180),result=[];
    // Support points of the pole and the single vertical head. No horizontal
    // repeater or imaginary roof corners may influence screen fitting.
    for(const [halfWidth,back,front,z] of [[.09,-.09,.09,0],
      ...[d.head_bottom_m,d.head_top_m].map(z=>[d.head_width_m/2,-d.head_depth_m/2,d.head_depth_m/2+.015,z])])
      for(const x of [-halfWidth,halfWidth])for(const y of [back,front])
        result.push([p[0]+scale*(m[0]*x+m[4]*y)/sx,p[1]+scale*(m[1]*x+m[5]*y)/metres,(p[2] || 0)+scale*z]);
    return result;
  }
  static extent(row,scale,viewport) {
    const points=this.corners(row,scale).map(p=>viewport.project(p));
    if(points.some(p=>!p.slice(0,2).every(Number.isFinite)))return NaN;
    return Math.max(...[0,1].map(axis=>Math.max(...points.map(p=>p[axis]))-Math.min(...points.map(p=>p[axis]))));
  }
  static fit(row,viewport,detail) {
    const p=this.policy,min=p[detail ? 'detail_min_pixels' : 'overview_min_pixels'],max=p[detail ? 'detail_max_pixels' : 'overview_max_pixels'];
    let scale=p.visual_scale,extent=this.extent(row,scale,viewport);
    if(!(extent>0))return {scale:1,extent:0};
    // Fit the complete projected body, including perspective/latitude and the
    // single head. Only one scalar changes: world heading and +Z stay invariant.
    // A small interior margin absorbs floating point/projection approximation.
    const target=Math.max(min+.25,Math.min(max-.25,extent));
    for(let i=0;i<5 && Math.abs(extent-target)>.02;i++) {
      scale*=target/extent;extent=this.extent(row,scale,viewport);
      if(!(extent>0) || !Number.isFinite(scale))return {scale:1,extent:0};
    }
    return {scale,extent};
  }
  prepareView(viewport) {
    if(!viewport || !Number.isFinite(viewport.zoom))return false;
    const key=JSON.stringify(['longitude','latitude','zoom','pitch','bearing','width','height','altitude','orthographic'].map(k=>viewport[k]));
    if(key===this.viewKey)return false;
    this.detail=this.detail===null ? viewport.zoom>=16.4 : viewport.zoom>=(this.detail ? this.constructor.policy.detail_off : this.constructor.policy.detail_on);
    const inView=row=>{
      const p=viewport.project(row.Signal_Geometry.anchor),margin=this.constructor.policy.detail_max_pixels;
      return p.slice(0,2).every(Number.isFinite) && p[0]>=-margin && p[0]<=viewport.width+margin &&
        p[1]>=-margin && p[1]<=viewport.height+margin;
    };
    this.visible=(this.detail ? this.oriented : this.overview).filter(inView);
    this.visibleUnoriented=this.unoriented.filter(inView);
    const selected=new Set(this.visible.map(row=>row.Signal_Geometry));
    this.visibleLamps=(this.detail ? this.lamps : this.overviewLamps).filter(row=>selected.has(row.Signal_Geometry));
    this.frame=new Map();
    for(const row of [...this.visible,...this.visibleUnoriented]) {
      const fit=this.constructor.fit(row,viewport,this.detail),g=row.Signal_Geometry;
      this.frame.set(g,{...fit,transform:this.constructor.scaled(g.transform || this.constructor.transform([0,1]),fit.scale)});
    }
    this.lampFrame=new Map(this.visibleLamps.map(row=>[row,this.constructor.scaled(row.Signal_Lamp_Transform,this.frame.get(row.Signal_Geometry).scale)]));
    this.viewKey=key;this.viewBuilds++;this.revision++;
    return true;
  }
  viewProps(id) {
    const frame=this.frame,lamps=this.lampFrame;
    if(id==='signals' || id==='signal-unoriented')return {data:id==='signals' ? this.visible ?? this.oriented : this.visibleUnoriented ?? this.unoriented,
      getTransformMatrix:row=>row && (frame.get(row.Signal_Geometry)?.transform || row.Signal_Geometry.transform),
      updateTriggers:{getTransformMatrix:this.revision}};
    if(id==='signal-lamps')return {data:this.visibleLamps ?? this.lamps,
      getTransformMatrix:row=>row && (lamps?.get(row) || row.Signal_Lamp_Transform),updateTriggers:{getTransformMatrix:this.revision}};
    return null;
  }
  updateLayers(layers,viewport) {
    if(!this.prepareView(viewport))return layers;
    return layers.map(layer=>{
      const props=this.viewProps(layer.id);
      return props ? layer.clone({...props,updateTriggers:{...layer.props.updateTriggers,...props.updateTriggers}}) : layer;
    });
  }
  layers(deck,viewport=null) {
    if(typeof deck.SimpleMeshLayer!=='function')throw new Error('deck.gl 9.1.14: SimpleMeshLayer no disponible');
    this.prepareView(viewport);const meshes=this.constructor.meshes();
    const meshProps={getPosition:d=>d.Signal_Geometry.anchor,getColor:[255,255,255,255],sizeScale:1,material:false,pickable:true,
      parameters:{depthCompare:'less-equal',depthWriteEnabled:true,cullMode:'back'}};
    return [
      new deck.SimpleMeshLayer({...meshProps,id:'signals',mesh:meshes.body,...this.viewProps('signals')}),
      new deck.SimpleMeshLayer({...meshProps,id:'signal-unoriented',mesh:meshes.pole,...this.viewProps('signal-unoriented')}),
      new deck.SimpleMeshLayer({...meshProps,id:'signal-lamps',mesh:meshes.lamp,...this.viewProps('signal-lamps'),
        getColor:d=>this.constructor.lampColor(d,'UNKNOWN')})
    ];
  }
  static stateProps(id,stateAt,time,revision=0) {
    if(id==='signal-lamps')return {getColor:row=>this.lampColor(row,stateAt(row.system_id,row.group_id,time)),
      updateTriggers:{getColor:[time,revision]}};
    return null;
  }
  tooltip(row,stateAt,time) {
    if(!row?.Signal_Geometry)return null;
    const members=this.detail===false ? this.clusters.get(row.Signal_Geometry.intersection_key) || [row] : [row];
    const names={RED:'Rojo',YELLOW:'Amarillo',GREEN:'Verde',REDYELLOW:'Rojo y amarillo',OFF:'Apagado',UNKNOWN:'Sin estado registrado'};
    return {text:(members.length>1 ? 'Interseccion: '+members.length+' senales; icono del acceso '+row.Link_ID : 'Semaforo: '+row.Link_ID)+
      '\n'+members.map(r=>r.Link_ID+': '+(names[stateAt(r.system_id,r.group_id,time)] || names.UNKNOWN)).join('\n'),
      style:{maxWidth:'320px',whiteSpace:'pre-line',fontSize:'12px',backgroundColor:'#17232d',color:'#fff'}};
  }
  snapshot() {
    return {version:this.constructor.version,axes:'X east; Y north; Z up; local face +Y',
      dimensions:{...this.constructor.dimensions,source:'explicit_visual_assumptions'},
      screen_policy:this.constructor.policy,detail:this.detail,view_builds:this.viewBuilds,
      visible:(this.visible ?? this.oriented).length,intersections:this.clusters.size,
      corrected_anchors:this.records.filter(row=>row.Signal_Geometry.placement?.corrected).length,
      clusters:Array.from(this.clusters,([key,members])=>({key,representative:members[0].signal_id,
        members:members.map(row=>({system_id:row.system_id,group_id:row.group_id,signal_id:row.signal_id,Link_ID:row.Link_ID}))})),
      rendered:(this.visible ?? this.oriented).map(row=>({signal_id:row.signal_id,Link_ID:row.Link_ID,...this.frame.get(row.Signal_Geometry)})),
      total:this.records.length,oriented:this.oriented.length,unoriented:this.unoriented.length,issues:this.issues,
      records:this.records.map(row=>({system_id:row.system_id,group_id:row.group_id,signal_id:row.signal_id,
        Link_ID:row.Link_ID,lane_ids:row.lane_ids,geometry:row.Signal_Geometry}))};
  }
}
