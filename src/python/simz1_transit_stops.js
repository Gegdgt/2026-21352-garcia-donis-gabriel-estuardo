/* Static catalog annotations, not native traffic or signal states. deck.gl 9.1.14.
 * One shared SVG atlas + three instanced layers, independent of stop count.
 * Anchor coordinates never move. Direction arrows use world ENU, not camera yaw.
 */
class SimZ1TransitStops {
  static version='simz1-stop-signs-v2';
  static systems=Object.freeze({transmetro:'Transmetro',tubus:'TuBus',transurbano:'Transurbano',urbano:'Urbano',extraurbano:'Extraurbano'});
  static colors=Object.freeze({green:'#20a65a',blue:'#2388dc'});
  static policy=Object.freeze({ordinary:{on:16,off:15.7},labels:{on:18,off:17.7}});
  static ids=['transit-stop-directions','transit-stop-signs','transit-stop-names'];
  static atlas() {
    if(this.cachedAtlas)return this.cachedAtlas;
    const mapping={},icons=[],columns=9;
    const variants=['green','blue','mixed','green-transfer','blue-transfer','mixed-transfer',
                    'green-cluster','blue-cluster','mixed-cluster']
      .flatMap(name=>['center','left','right'].map(side=>({name,side})));
    for(const [index,{name,side}] of variants.entries()) {
      const key=side==='center' ? name : name+'-'+side,center={center:48,left:22,right:74}[side];
      const x=(index%columns)*96,y=Math.floor(index/columns)*72;
      mapping[key]={x,y,width:96,height:72,anchorX:48,anchorY:64,mask:false};
      const mixed=name.startsWith('mixed'),fill=name.startsWith('green') ? this.colors.green : this.colors.blue;
      icons.push(`<g transform="translate(${x},${y})">
        <path d="M${center} 47L48 64M45 64H51M48 61V67" stroke="#f3f7fa" stroke-width="1.5" fill="none"/>
        <g transform="translate(${center-24},0)">
        ${name.endsWith('cluster') ? '<path d="M12 3H44V42M16 1H47V38" stroke="#fff" stroke-width="2" fill="none"/>' : ''}
        <rect x="7" y="5" width="34" height="42" rx="4" fill="${mixed ? this.colors.green : fill}" stroke="#f3f7fa" stroke-width="2"/>
        ${mixed ? `<path d="M24 6H37Q40 6 40 10V42Q40 46 36 46H24Z" fill="${this.colors.blue}"/>` : ''}
        <path d="M15 14Q15 11 19 11H29Q33 11 33 14V33H15Z" fill="#fff"/>
        <path d="M18 15H30V24H18Z" fill="#17232d"/>
        <path d="M18 28H21V31H18ZM27 28H30V31H27ZM16 33H20V36H16ZM28 33H32V36H28Z" fill="#17232d"/>
        ${name.endsWith('transfer') ? '<path d="M10 41H38M10 41L14 38M38 41L34 44" stroke="#fff" stroke-width="2" fill="none"/>' : ''}
        </g></g>`);
    }
    const width=columns*96,height=Math.ceil(variants.length/columns)*72;
    this.cachedAtlas={url:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${icons.join('')}</svg>`),mapping};
    return this.cachedAtlas;
  }
  constructor(spec,identity,spatial=null) {
    this.spec=spec || {};this.records=[];this.issues=Array.isArray(spec?.issues) ? [...spec.issues] : [];this.zoom=null;
    this.bands={ordinary:false,labels:false};this.data=[];this.labels=[];this.arrows=[];
    this.clusterCache=new Map();this.displayKey=null;
    if(!spec || spec.available!==true)return;
    if(spec.schema_version!=='simz1-stop-display-v1' ||
       ['run_id','iteration','run_manifest_sha256'].some(key=>spec.identity?.[key]!==identity?.[key])) {
      this.issues.push({reason:'stop_identity_mismatch'});return;
    }
    if(!Array.isArray(spec.records)){this.issues.push({reason:'invalid_stop_records'});return;}
    const ids=new Set();
    for(const row of spec.records) {
      if(!row || typeof row!=='object'){this.issues.push({reason:'invalid_stop_record'});continue;}
      const valid=Array.isArray(row.position) && row.position.length===2 && row.position.every(Number.isFinite) &&
        Math.abs(row.position[0])<=180 && Math.abs(row.position[1])<85;
      const catalogOnly=row.annotation_kind==='catalog_only';
      const reason=!valid ? 'invalid_stop_position' : !row.transit_stop || !row.stop_id || ids.has(row.stop_id) ? 'invalid_stop_identity' :
        catalogOnly ? (row.native_access_status!=='unmapped' || row.Link_ID || Number.isFinite(row.bearing_degrees) ||
          !row.coordinate_evidence?.element ? 'invalid_catalog_annotation' : null) :
        !Number.isFinite(row.bearing_degrees) || !row.Link_ID || !row.direction ? 'missing_stop_access' : null;
      const evidenceReason=
        !Array.isArray(row.sources) || !row.sources.length || !Array.isArray(row.services) || !row.services.length ||
          row.sources.some(s=>!s?.source_id) || row.services.some(s=>!Object.hasOwn(this.constructor.systems,s?.system) ||
            !s.service_id || !s.line || !s.direction) ? 'missing_stop_evidence' :
        valid && spatial && ((!catalogOnly && !spatial.allowed.has(row.Link_ID)) || !spatial.contains(row.position)) ? 'outside_replay_domain' : null;
      if(reason || evidenceReason){this.issues.push({stop_id:row.stop_id,reason:reason || evidenceReason});continue;}
      ids.add(row.stop_id);
      const green=row.services.some(s=>s.system==='transmetro'),blue=row.services.some(s=>s.system!=='transmetro');
      const icon=(green && blue ? 'mixed' : green ? 'green' : 'blue')+(row.transfer ? '-transfer' : '');
      this.records.push({...row,icon});
    }
    this.records.sort((a,b)=>a.stop_id.localeCompare(b.stop_id));
    const byId=new Map(this.records.map(row=>[row.stop_id,row]));
    for(const row of this.records) {
      const opposite=(row.opposed_stop_ids || []).filter(id=>byId.get(id)?.opposed_stop_ids?.includes(row.stop_id));
      // Only explicit reciprocal pairs get two screen-label wings. The cross
      // and leader tip remain at the source anchor; no nearest-neighbour grouping.
      row.sign_side=opposite.length===1 ? (row.stop_id.localeCompare(opposite[0])<0 ? 'left' : 'right') : 'center';
    }
  }
  static arrow(row) {
    const p=row.position,angle=row.bearing_degrees*Math.PI/180,u=[Math.sin(angle),Math.cos(angle)],v=[u[1],-u[0]];
    const at=(forward,right)=>[p[0]+(u[0]*forward+v[0]*right)/(111320*Math.cos(p[1]*Math.PI/180)),
                               p[1]+(u[1]*forward+v[1]*right)/110574];
    // A short direction glyph, not an inferred route or repositioned platform.
    return {stop_id:row.stop_id,path:[at(2,0),at(5,0),at(4,1),at(5,0),at(4,-1)]};
  }
  clusters(level) {
    if(this.clusterCache.has(level))return this.clusterCache.get(level);
    const cells=new Map(),data=[],scale=512*2**level/64;
    for(const row of this.records) {
      // Preserve documented interchanges at every distance. Other grouping is
      // a view aggregate, never a new stop, transfer or shared native platform.
      if(row.transfer){data.push(row);continue;}
      const [lon,lat]=row.position,sin=Math.sin(lat*Math.PI/180);
      const key=Math.floor((lon+180)/360*scale)+':'+
        Math.floor((.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*scale);
      if(!cells.has(key))cells.set(key,[]);
      cells.get(key).push(row);
    }
    for(const [key,members] of cells) {
      if(members.length===1){data.push(members[0]);continue;}
      const services=members.flatMap(row=>row.services),green=services.some(s=>s.system==='transmetro'),
        blue=services.some(s=>s.system!=='transmetro');
      data.push({transit_stop:true,display_cluster:true,stop_id:'view-cluster:'+level+':'+key,
        position:members[0].position,members,icon:(green && blue ? 'mixed' : green ? 'green' : 'blue')+'-cluster',
        sign_side:'center'});
    }
    this.clusterCache.set(level,data);return data;
  }
  setZoom(zoom) {
    if(!Number.isFinite(zoom))return false;
    this.zoom=zoom;let changed=false;
    for(const [name,rule] of Object.entries(this.constructor.policy)) {
      const visible=this.bands[name] ? zoom>=rule.off : zoom>=rule.on;
      if(visible!==this.bands[name]){this.bands[name]=visible;changed=true;}
    }
    const level=Math.max(0,Math.min(15,Math.floor(zoom))),key=this.bands.ordinary ? 'detail' : 'clusters:'+level;
    if(!changed && key===this.displayKey)return false;
    this.displayKey=key;
    this.data=this.bands.ordinary ? this.records : this.clusters(level);
    this.labels=this.bands.labels ? this.data : [];
    this.arrows=this.bands.ordinary ? this.data.filter(row=>Number.isFinite(row.bearing_degrees))
      .map(row=>this.constructor.arrow(row)) : [];
    return true;
  }
  layers(deck,zoom) {
    this.setZoom(zoom);const atlas=this.constructor.atlas();
    const parameters={depthCompare:'always',depthWriteEnabled:false};
    return [
      new deck.PathLayer({id:'transit-stop-directions',data:this.arrows,getPath:d=>d.path,getColor:[220,233,244,220],
        getWidth:1.25,widthUnits:'pixels',widthMinPixels:0,widthMaxPixels:1.25,pickable:false,parameters}),
      new deck.IconLayer({id:'transit-stop-signs',data:this.data,iconAtlas:atlas.url,iconMapping:atlas.mapping,
        getPosition:d=>d.position,getIcon:d=>d.icon+(d.sign_side==='center' ? '' : '-'+d.sign_side),
        getSize:d=>d.display_cluster ? 44 : d.transfer ? 50 : 46,
        sizeUnits:'pixels',sizeMinPixels:0,sizeMaxPixels:50,billboard:true,getAngle:0,pickable:true,
        alphaCutoff:0.15,parameters}),
      new deck.TextLayer({id:'transit-stop-names',data:this.labels,getPosition:d=>d.position,
        getText:d=>d.name+(d.transfer ? ' ⇄' : ''),getSize:11,sizeUnits:'pixels',sizeMaxPixels:11,
        getPixelOffset:[15,0],getTextAnchor:'start',getAlignmentBaseline:'center',billboard:true,
        getColor:[228,239,246,255],background:true,getBackgroundColor:[16,24,32,210],backgroundPadding:[2,1],
        characterSet:'auto',fontFamily:'system-ui, sans-serif',pickable:false,parameters})
    ];
  }
  updateLayers(layers,zoom) {
    if(!this.setZoom(zoom))return layers;
    return layers.map(layer=>layer.id==='transit-stop-signs' ? layer.clone({data:this.data}) :
      layer.id==='transit-stop-names' ? layer.clone({data:this.labels}) :
      layer.id==='transit-stop-directions' ? layer.clone({data:this.arrows}) : layer);
  }
  static tooltip(row) {
    if(!row?.transit_stop)return null;
    const style={maxWidth:'380px',whiteSpace:'pre-line',fontSize:'12px',backgroundColor:'#17232d',color:'#fff'};
    if(row.display_cluster)return {text:'Agrupación visual: '+row.members.length+' paradas del catálogo\n'+
      row.members.slice(0,12).map(stop=>stop.name+' — '+stop.services.map(s=>s.service+' '+s.line).join(', ')).join('\n')+
      (row.members.length>12 ? '\n… y '+(row.members.length-12)+' más' : '')+
      '\nAcérquese para ver cada plataforma, operador y sentido. No indica transbordo ni uso en la simulación.',style};
    if(row.annotation_kind==='native_weekday_scenario_stop')return {text:'Parada configurada: '+row.name+'\n'+
      row.services.map(s=>s.service+' · '+s.line+' → '+s.direction).join('\n')+
      '\nEnlace nativo: '+row.Link_ID+'\nPosición nativa: extremo de enlace (aproximación de escenario).'+
      '\nFuente cartográfica: '+row.coordinate_evidence?.source_id+
      '\nHorario/ubicación operativa actual no certificados; no es una parada de entrada/salida del mapa.',style};
    const usage=row.simulation_usage?.status==='not_configured' ? 'Esta corrida no tiene transporte público configurado.' :
      'Uso efectivo por la simulación: no acreditado.';
    return {text:'Parada del catálogo: '+row.name+'\n'+row.services.map(service=>
      service.service+' · '+service.line+' → '+service.direction+'\nOperador: '+(service.operator || 'pendiente')).join('\n')+
      (row.annotation_kind==='catalog_only' ? '\nSentidos según relaciones OSM; enlace/carril MATSim sin asociar.' :
        '\nAcceso revisado: '+row.Link_ID+' · '+row.direction)+
      (row.transfer ? '\nTransbordo documentado: '+row.transfer.name : '')+
      (row.opposed_stop_ids?.length ? '\nParada enfrentada: '+row.opposed_stop_ids.join(', ') : '')+
      '\n'+usage+'\nRevisión: '+row.review_date+'; vigencia operativa para la fecha del replay sin confirmar.'+
      (row.coordinate_evidence ? '\nCoordenada OSM: '+row.coordinate_evidence.element+' · '+row.coordinate_evidence.timestamp : '')+
      '\nFuentes: '+row.sources.map(source=>source.source_id+(source.published_on ? ' ('+source.published_on+')' : '')).join(', '),style};
  }
  snapshot() {
    return {version:this.constructor.version,status:this.spec.status || 'stop_catalog_unavailable',
      identity:this.spec.identity,scope:this.spec.scope,catalog_sha256:this.spec.catalog_sha256,
      source_registry_sha256:this.spec.source_registry_sha256,
      mapping_sha256:this.spec.mapping_sha256,network_sha256:this.spec.network_sha256,
      catalog_review_date:this.spec.review_date,source_station_records:this.spec.source_station_records,
      simulation_usage:this.spec.simulation_usage,pending:this.spec.pending,native_mapping_issues:this.spec.native_mapping_issues,
      accepted:this.records.length,visible:this.data.length,zoom:this.zoom,zoom_policy:this.constructor.policy,
      represented:this.data.reduce((sum,row)=>sum+(row.members?.length || 1),0),display_mode:this.displayKey,
      bands:{...this.bands},issues:this.issues,records:this.records,
      marker_policy:'exact source anchors; fixed pixel bus pictograms; cached view clusters anchored at a member; protected transfers; no inferred native links; below vehicles'};
  }
}
if(typeof module!=='undefined' && module.exports)module.exports=SimZ1TransitStops;
