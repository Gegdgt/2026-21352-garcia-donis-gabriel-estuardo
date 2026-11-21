/* Native aggregate evidence has no individual positions. These layers only
 * colour recorded network geometry; they never contribute vehicle markers. */
class SimZ1AggregateView {
  static identityKeys=['run_id','iteration','run_manifest_sha256','source_version'];
  static optionalIdentityKeys=['visual_policy','checkpoint_library_root'];
  static labels={carro:'Carros',moto:'Motos',pesado:'Camiones',bus:'Buses',unknown:'Sin familia'};
  static count(value){return Number.isSafeInteger(value)&&value>=0;}
  static clock(value){
    if(!Number.isFinite(value))return 'Sin dato';
    const t=Math.max(0,Math.floor(value)),h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=t%60;
    return [h,m,s].map(x=>String(x).padStart(2,'0')).join(':');
  }
  static familyAllowed(family,filter){
    return filter==='all'||filter==='private'&&['carro','moto'].includes(family)||
      ({car:'carro',motorcycle:'moto',freight:'pesado',bus:'bus'})[filter]===family;
  }
  static validate(payload,identity,time){
    const fail=detail=>{throw new Error('Contrato agregado incompatible: '+detail);};
    if(!payload||payload.schema_version!==1||payload.no_positions!==true||
       [...SimZ1AggregateView.identityKeys,...SimZ1AggregateView.optionalIdentityKeys.filter(k=>identity[k]!=null||payload.identity?.[k]!=null)]
         .some(key=>payload.identity?.[key]!==identity[key]))fail('identidad');
    if(payload.time_seconds!==time||!Number.isFinite(time)||time<0)fail('instante');
    if(!Array.isArray(payload.origins)||!Array.isArray(payload.links))fail('colecciones');
    const origins=new Set(),links=new Set();
    for(const row of payload.origins){
      const key=JSON.stringify([row.origin_link,row.family]);
      if((row.origin_link!==null&&(typeof row.origin_link!=='string'||!row.origin_link))||typeof row.family!=='string'||
         origins.has(key))fail('origen duplicado o inválido');
      origins.add(key);
      for(const field of ['scheduled_total','scheduled_due','requested','entered','waiting_admission','retired_waiting','arrived','active_origin_cohort'])
        if(!SimZ1AggregateView.count(row[field]))fail('contador de origen '+field);
      if(row.scheduled_due>row.scheduled_total||row.requested>row.scheduled_due||row.entered>row.requested||
         row.arrived>row.entered||row.waiting_admission+row.entered+row.retired_waiting!==row.requested)fail('balance de origen');
      for(const field of ['oldest_pending_request','latest_entry'])
        if(row[field]!=null&&(!Number.isFinite(row[field])||row[field]<0||row[field]>time))fail('tiempo de origen');
      if(row.hourly!=null&&(!Array.isArray(row.hourly)||row.hourly.some(h=>!Number.isSafeInteger(h.hour)||h.hour<0||h.hour>23||
          ['scheduled','requested','entered'].some(k=>!SimZ1AggregateView.count(h[k]))||
          ['arrived','waiting_admission_end'].some(k=>h[k]!=null&&!SimZ1AggregateView.count(h[k])))))
        fail('evolución horaria');
    }
    for(const row of payload.links){
      if(typeof row.link_id!=='string'||!row.link_id||links.has(row.link_id)||!SimZ1AggregateView.count(row.active_count))fail('enlace');
      links.add(row.link_id);
      if(!row.families||typeof row.families!=='object'||Array.isArray(row.families)||
         Object.values(row.families).some(x=>!SimZ1AggregateView.count(x))||
         Object.values(row.families).reduce((a,b)=>a+b,0)!==row.active_count)fail('familias del enlace');
      for(const field of ['last_change_time','latest_entry','latest_leave'])
        if(row[field]!=null&&(!Number.isFinite(row[field])||row[field]<0||row[field]>time))fail('transición del enlace');
      if(row.time_since_change!=null&&(!Number.isFinite(row.time_since_change)||row.time_since_change<0))fail('edad de asociación');
      for(const field of ['entry_count','leave_count'])if(row[field]!=null&&!SimZ1AggregateView.count(row[field]))fail('conteo de transiciones');
    }
    return payload;
  }
  constructor({identity,endpoint='/api/aggregate',geometry={},spatial=null,document,fetch:fetcher,onChange=()=>{},stepSeconds=60,persistenceSeconds=300}){
    this.identity={};for(const k of [...SimZ1AggregateView.identityKeys,...SimZ1AggregateView.optionalIdentityKeys])
      if(identity[k]!=null)this.identity[k]=identity[k];
    this.endpoint=endpoint;this.document=document;this.fetcher=fetcher;this.onChange=onChange;
    this.persistenceSeconds=Number.isFinite(persistenceSeconds)&&persistenceSeconds>0?persistenceSeconds:300;
    this.stepSeconds=Math.max(1,stepSeconds);this.paths=new Map();this.names=new Map();
    for(const [id,row] of Object.entries(geometry)){
      if(!Array.isArray(row.path)||row.path.length<2||row.path.some(p=>!Array.isArray(p)||p.length<2||!p.slice(0,2).every(Number.isFinite)))continue;
      const paths=spatial?spatial.paths([{Link_ID:id,path:row.path}]):[{path:row.path}];
      this.paths.set(id,paths.filter(x=>Array.isArray(x.path)&&x.path.length>1).map(x=>x.path));
      this.names.set(id,row.osm_tags?.name||row.name||id);
    }
    this.enabled={origins:true,links:true};this.filter='all';this.route='';this.time=null;
    this.data=null;this.status='idle';this.error=null;this.selected=null;this.sequence=0;this.controller=null;
    this.cache=new Map();this.pendingKey=null;this.lastAttempt=null;
    this.playing=false;this.lastClockTime=null;this.awaitingSeek=null;
    this.metrics={requests:0,completed:0,failed:0,aborted:0,stale:0,cacheHits:0};
    this.mount();
  }
  el(tag,text){const node=this.document.createElement(tag);if(text!=null)node.textContent=text;return node;}
  mount(){
    const section=this.el('section');section.id='simz1-aggregate-view';section.setAttribute('aria-label','Lectura agregada del tráfico');
    const bar=this.el('div');bar.className='simz1-aggregate-bar';
    bar.append(this.el('strong','Capas agregadas'));
    for(const [key,label] of [['origins','Pendientes en origen'],['links','Asociación por enlace']]){
      const control=this.el('label'),input=this.el('input');input.type='checkbox';input.checked=true;
      input.id='simz1-aggregate-'+key;input.onchange=()=>{this.enabled[key]=input.checked;this.onChange();};
      control.append(input,this.el('span',label));bar.append(control);
    }
    this.originSelect=this.el('select');this.originSelect.setAttribute('aria-label','Inspeccionar origen');
    this.originSelect.onchange=()=>{if(this.originSelect.value)this.select('origin',this.originSelect.value);};
    bar.append(this.originSelect);
    this.linkInput=this.el('input');this.linkInput.type='search';this.linkInput.placeholder='ID de enlace';
    this.linkInput.setAttribute('aria-label','Enlace para inspeccionar');
    const inspect=this.el('button','Ver enlace');inspect.type='button';inspect.onclick=()=>this.select('link',this.linkInput.value.trim());
    this.linkInput.onkeydown=e=>{if(e.key==='Enter')inspect.onclick();};bar.append(this.linkInput,inspect);
    this.statusNode=this.el('div');this.statusNode.id='simz1-aggregate-status';this.statusNode.setAttribute('role','status');
    this.retry=this.el('button','Reintentar agregados');this.retry.type='button';this.retry.hidden=true;
    this.retry.onclick=()=>{if(this.time!=null)this.request(this.time,true);};
    const legend=this.el('p','Ámbar: espera fuera de la red. Azul: vehículos asociados al último enlace nativo. Los trazos representan enlaces, no posiciones ni cuerpos.');
    legend.className='simz1-aggregate-legend';
    this.details=this.el('details');this.details.id='simz1-aggregate-details';
    this.detailsSummary=this.el('summary','Seleccione un origen o enlace para consultar sus conteos');
    this.detailBody=this.el('div');this.detailBody.className='simz1-aggregate-detail-body';
    this.details.append(this.detailsSummary,this.detailBody);section.append(bar,this.statusNode,this.retry,legend,this.details);
    const host=this.document.getElementById('simz1-controls');if(host)host.append(section);
    this.section=section;this.refreshPanel();
  }
  update(time,{paused=true,family='all',route=''}={}){
    if(!Number.isFinite(time))return;
    const changed=this.filter!==family||this.route!==route;
    this.filter=family;this.route=route;
    if(changed){this.refreshPanel();this.onChange();}
    let exactSeek=false;
    if(this.awaitingSeek!==null){
      if(Math.floor(time)!==this.awaitingSeek)return;
      this.awaitingSeek=null;exactSeek=true;
    }
    const backwards=this.lastClockTime!==null&&time<this.lastClockTime;
    const pauseChanged=paused&&this.playing;
    if(backwards||pauseChanged)this.invalidate();
    let target=Math.max(0,paused||exactSeek?Math.floor(time):Math.floor(time/this.stepSeconds)*this.stepSeconds);
    // A seek at 06:30:22 may resume before the next minute. Do not replace its
    // exact observation with the earlier 06:30:00 bucket during forward play.
    if(!paused&&!backwards&&!exactSeek&&this.lastClockTime!==null&&this.time!==null)target=Math.max(target,this.time);
    this.lastClockTime=time;this.playing=!paused;
    const timeChanged=this.time!==target;this.time=target;
    if(this.status==='error'){this.refreshPanel();return;}
    if(this.pendingKey!==null){
      // One flight during forward playback. Its response will be displayed
      // with its own as_of; completion requests only the latest pending time.
      if(paused&&this.pendingKey!==target){this.invalidate();this.request(target);}
      else if(timeChanged)this.refreshPanel();
      return;
    }
    if(timeChanged||this.status==='idle')this.request(target,false,this.playing);
  }
  invalidate(){
    if(this.controller){this.controller.abort();this.metrics.aborted++;}
    this.sequence++;this.controller=null;this.pendingKey=null;this.data=null;
    if(this.status!=='error')this.status='idle';this.refreshPanel();this.onChange();
  }
  seek(time){
    if(!Number.isFinite(time))return;
    this.awaitingSeek=Math.max(0,Math.floor(time));this.time=this.awaitingSeek;
    this.invalidate();this.lastClockTime=null;
  }
  async request(time,force=false,keepVisible=false){
    if(this.pendingKey===time)return;
    if(!force&&this.lastAttempt===time&&this.status==='error')return;
    if(this.controller){this.controller.abort();this.metrics.aborted++;}
    const serial=++this.sequence;this.controller=null;this.pendingKey=null;
    if(this.cache.has(time)&&!force){
      this.data=this.cache.get(time);this.metrics.cacheHits++;this.status='ready';this.refreshPanel();this.onChange();return;
    }
    this.controller=new AbortController();const controller=this.controller;
    this.pendingKey=time;this.lastAttempt=time;if(!keepVisible)this.data=null;
    this.error=null;this.status=this.data?'ready':'loading';this.refreshPanel();this.onChange();
    this.metrics.requests++;
    const params=new URLSearchParams({time:String(time),...Object.fromEntries(Object.entries(this.identity).map(([k,v])=>[k,String(v)]))});
    try{
      const response=await this.fetcher(this.endpoint+'?'+params.toString(),{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const payload=await response.json();
      if(serial!==this.sequence){this.metrics.stale++;return;}
      SimZ1AggregateView.validate(payload,this.identity,time);
      this.cache.set(time,payload);while(this.cache.size>4)this.cache.delete(this.cache.keys().next().value);
      this.data=payload;this.status='ready';this.metrics.completed++;
    }catch(error){
      if(serial!==this.sequence){this.metrics.stale++;return;}
      if(controller.signal.aborted)return;
      this.error=String(error?.message||error);this.data=null;this.status='error';this.metrics.failed++;
    }finally{
      if(serial===this.sequence){
        this.pendingKey=null;this.controller=null;this.refreshPanel();this.onChange();
        if(this.status==='ready'&&this.playing&&this.awaitingSeek===null&&this.time!==time)this.request(this.time,false,true);
      }
    }
  }
  origins(){return this.data?.origins.filter(r=>SimZ1AggregateView.familyAllowed(r.family,this.filter))||[];}
  linkCount(row){return Object.entries(row.families).reduce((n,[family,count])=>n+(SimZ1AggregateView.familyAllowed(family,this.filter)?count:0),0);}
  groupedOrigins(){
    const grouped=new Map();
    for(const row of this.origins()){
      if(!grouped.has(row.origin_link))grouped.set(row.origin_link,{id:row.origin_link,count:0,rows:[]});
      const entry=grouped.get(row.origin_link);entry.count+=row.waiting_admission;entry.rows.push(row);
    }
    return [...grouped.values()].sort((a,b)=>b.count-a.count||String(a.id).localeCompare(String(b.id)));
  }
  layerRows(){
    const result={origins:[],links:[]};
    if(this.status!=='ready'||this.route)return result;
    for(const entry of this.groupedOrigins())if(entry.count>0)
      for(const path of this.paths.get(entry.id)||[])result.origins.push({aggregate_kind:'origin',link_id:entry.id,count:entry.count,path});
    for(const row of this.data.links){const count=this.linkCount(row);if(count>0)
      for(const path of this.paths.get(row.link_id)||[])result.links.push({aggregate_kind:'link',link_id:row.link_id,count,path});}
    return result;
  }
  layers(deck){
    const rows=this.layerRows();
    return ['links','origins'].map(kind=>new deck.PathLayer({id:'simz1-aggregate-'+kind,
      data:this.enabled[kind]?rows[kind]:[],getPath:d=>d.path,
      getColor:d=>kind==='origins'?[255,183,78,220]:[52,Math.max(90,205-Math.round(20*Math.log2(1+d.count))),235,210],
      getWidth:d=>Math.min(kind==='origins'?9:7,2+Math.log2(1+d.count)),widthUnits:'pixels',widthMinPixels:0,
      pickable:true,billboard:true,capRounded:true,jointRounded:true,
      parameters:{depthCompare:'always',depthWriteEnabled:false}}));
  }
  select(kind,id){
    if(!id)return false;this.selected={kind,id};this.details.open=true;this.refreshPanel();return true;
  }
  click(info){const object=info?.object;if(!object?.aggregate_kind)return false;return this.select(object.aggregate_kind,object.link_id);}
  tooltip(info){const object=info?.object;if(!object?.aggregate_kind)return null;
    return {text:(this.names.get(object.link_id)||object.link_id)+'\n'+object.count+' '+
      (object.aggregate_kind==='origin'?'pendientes fuera de la red':'asociados al enlace')+'\nNo representa posiciones individuales.'};}
  clear(node){if(node.replaceChildren)node.replaceChildren();else{while(node.firstChild)node.removeChild(node.firstChild);node.textContent='';}}
  paragraph(text){this.detailBody.append(this.el('p',text));}
  table(headers,values){
    const table=this.el('table'),head=this.el('thead'),tr=this.el('tr');for(const text of headers)tr.append(this.el('th',text));head.append(tr);table.append(head);
    const body=this.el('tbody');for(const valuesRow of values){const row=this.el('tr');for(const text of valuesRow)row.append(this.el('td',String(text)));body.append(row);}table.append(body);this.detailBody.append(table);
  }
  coverage(value){
    if(typeof value==='string')return value;
    if(value&&typeof value==='object')return Object.entries(value).map(([k,v])=>k+': '+(v==null?'sin dato':typeof v==='object'?JSON.stringify(v):v)).join(' · ');
    return 'Cobertura no detallada';
  }
  coverageCount(key){
    const value=this.data?.coverage?.[key];
    if(SimZ1AggregateView.count(value))return this.filter==='all'?value:null;
    if(value&&typeof value==='object'&&!Array.isArray(value)){
      const entries=Object.entries(value).filter(([f])=>SimZ1AggregateView.familyAllowed(f,this.filter));
      return entries.length&&entries.every(([,n])=>SimZ1AggregateView.count(n))?entries.reduce((n,[,c])=>n+c,0):null;
    }
    return null;
  }
  persistence(row){
    if(!Number.isFinite(row.time_since_change))return null;
    return this.linkCount(row)>0&&row.time_since_change>=this.persistenceSeconds;
  }
  refreshPanel(){
    this.retry.hidden=this.status!=='error';
    if(this.route)this.statusNode.textContent='Sin desglose agregado para la ruta elegida. El filtro de ruta sigue aplicado a los cuerpos.';
    else if(this.status==='error')this.statusNode.textContent='Agregados no disponibles para '+SimZ1AggregateView.clock(this.time)+'. '+this.error;
    else if(this.status!=='ready')this.statusNode.textContent='Cargando agregados de '+SimZ1AggregateView.clock(this.time)+'…';
    else{
      const pending=this.origins().reduce((n,r)=>n+r.waiting_admission,0),associated=this.data.links.reduce((n,r)=>n+this.linkCount(r),0);
      const unassociated=this.coverageCount('unassociated_active');
      this.statusNode.textContent='Datos al '+SimZ1AggregateView.clock(this.data.time_seconds)+' · Pendientes: '+pending+' · Asociados a enlaces: '+associated+
        ' · Activos sin enlace verificable: '+(unassociated??'Sin dato')+
        (this.pendingKey!==null||this.data.time_seconds!==this.time?' · Actualizando hacia '+SimZ1AggregateView.clock(this.time):'');
    }
    const previous=this.originSelect.value;this.clear(this.originSelect);
    const placeholder=this.el('option','Inspeccionar origen');placeholder.value='';this.originSelect.append(placeholder);
    for(const row of this.groupedOrigins())if(row.id!==null){
      const option=this.el('option',(this.names.get(row.id)||row.id)+' · '+row.count+' pendientes');option.value=row.id;this.originSelect.append(option);
    }
    this.originSelect.value=previous||'';this.clear(this.detailBody);
    if(!this.selected){this.detailsSummary.textContent='Seleccione un origen o enlace para consultar sus conteos';return;}
    const {kind,id}=this.selected;
    this.detailsSummary.textContent=(kind==='origin'?'Origen: ':'Enlace: ')+(this.names.get(id)||id);
    this.paragraph(id);
    if(this.status!=='ready'||this.route){this.paragraph('Sin datos agregados disponibles para este instante y filtro.');return;}
    if(kind==='origin'){
      const rows=this.origins().filter(r=>r.origin_link===id);
      if(!rows.length){this.paragraph('Origen sin cobertura para la familia elegida.');return;}
      this.table(['Familia / unidad','Programados día','Programados al corte','Solicitudes','Entradas','Pendientes','Retirados antes de entrar','Llegadas','Activos de origen'],rows.map(r=>[
        r.family==='bus'?'Expediciones de bus':SimZ1AggregateView.labels[r.family]||r.family,r.scheduled_total,r.scheduled_due,r.requested,r.entered,r.waiting_admission,r.retired_waiting,r.arrived,r.active_origin_cohort]));
      const oldest=rows.map(r=>r.oldest_pending_request).filter(Number.isFinite),latest=rows.map(r=>r.latest_entry).filter(Number.isFinite);
      this.paragraph('Solicitud pendiente más antigua: '+SimZ1AggregateView.clock(oldest.length?Math.min(...oldest):null)+
        ' · Última incorporación: '+SimZ1AggregateView.clock(latest.length?Math.max(...latest):null));
      this.paragraph('Pendientes fuera de la red; los activos de esta cohorte pueden estar en otros enlaces.');
      const hourly=new Map();for(const r of rows){
        for(const h of [...r.hourly||[]].filter(h=>h.hour*3600<=this.data.time_seconds).sort((a,b)=>a.hour-b.hour)){
          if(!hourly.has(h.hour))hourly.set(h.hour,{contributors:0,scheduled:0,requested:0,entered:0,arrived:0,waiting_admission:0});
          hourly.get(h.hour).contributors++;
          for(const k of ['scheduled','requested','entered','arrived','waiting_admission']){
            const value=k==='waiting_admission'?h.waiting_admission_end:h[k],bucket=hourly.get(h.hour);
            bucket[k]=bucket[k]===null||value==null?null:bucket[k]+value;
          }
        }
      }
      if(hourly.size){this.paragraph('Evolución horaria hasta '+SimZ1AggregateView.clock(this.data.time_seconds)+'. La última hora puede estar incompleta.');
        this.table(['Hora','Programados','Solicitudes','Entradas','Llegadas','Pendientes al corte'],[...hourly].sort((a,b)=>a[0]-b[0]).map(([h,r])=>
          [String(h).padStart(2,'0')+':00',...['scheduled','requested','entered','arrived','waiting_admission'].map(k=>r.contributors===rows.length?(r[k]??'Sin dato'):'Sin dato')]));}
      this.paragraph('Cobertura: '+this.coverage(rows[0].coverage||this.data.coverage));
    }else{
      const row=this.data.links.find(r=>r.link_id===id);
      if(!row){this.paragraph('Sin asociación registrada para este enlace en la respuesta; no acredita capacidad de recepción.');return;}
      this.table(['Familia','Asociados'],Object.entries(row.families).filter(([f])=>SimZ1AggregateView.familyAllowed(f,this.filter)).map(([f,n])=>[SimZ1AggregateView.labels[f]||f,n]));
      const transitionCount=(total,byFamily)=>{
        if(this.filter==='all')return total??'Sin dato';
        if(!byFamily)return 'Sin desglose por familia';
        return Object.entries(byFamily).filter(([f])=>SimZ1AggregateView.familyAllowed(f,this.filter)).reduce((n,[,v])=>n+v,0);
      };
      this.paragraph('Entradas registradas al enlace: '+transitionCount(row.entry_count,row.entry_families)+
        ' · Salidas registradas del enlace: '+transitionCount(row.leave_count,row.leave_families)+'. Transiciones de asociación; no acreditan despeje corporal.');
      this.paragraph('Último cambio de asociación: '+SimZ1AggregateView.clock(row.last_change_time)+
        ' · Última entrada: '+SimZ1AggregateView.clock(row.latest_entry)+' · Última salida: '+SimZ1AggregateView.clock(row.latest_leave));
      this.paragraph('Tiempo desde el último cambio de asociación: '+(Number.isFinite(row.time_since_change)?Math.floor(row.time_since_change)+' s':'Sin dato')+'. La ausencia de cambios no prueba inmovilidad corporal ni bloqueo irreversible.');
      const persistent=this.persistence(row);
      this.paragraph('Indicador de asociación persistente: '+(persistent===null?'Sin dato':persistent?'Sí':'No')+
        '. Criterio: al menos un asociado y '+this.persistenceSeconds+' s sin cambio de asociación ni evento de entrada/salida observado en el enlace completo. Es un indicador de acumulación, no una prueba de congestión física.');
      this.paragraph('Asociación nativa por enlace; posiciones individuales y espacio disponible no determinados.');
      this.paragraph('Cobertura: '+this.coverage(row.coverage||this.data.coverage));
    }
    if(!(this.paths.get(id)||[]).length)this.paragraph('Sin geometría representable en esta vista; los conteos siguen disponibles.');
  }
  snapshot(){return {status:this.status,time:this.time,as_of_seconds:this.data?.time_seconds??null,pending_time:this.pendingKey,
    identity:{...this.identity},enabled:{...this.enabled},filter:this.filter,route:this.route,
    selected:this.selected?{...this.selected}:null,no_positions:true,persistence_seconds:this.persistenceSeconds,vehicle_markers_created:0,metrics:{...this.metrics},error:this.error};}
}
if(typeof module!=='undefined'&&module.exports)module.exports={SimZ1AggregateView};
