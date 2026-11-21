// One ordered native series per system/group. Upper bound includes the exact
// timestamp, with original event order for multiple initialization states.
let signalTimelines = new Map();
for (const series of config.signal_replay?.series || []) {
  const key = JSON.stringify([series.system_id,series.group_id]);
  if (signalTimelines.has(key)) throw new Error('Duplicate native signal group: '+key);
  signalTimelines.set(key,series.states);
}
function signalObservationAt(system, group, time) {
  const events = signalTimelines.get(JSON.stringify([system,group])) || [];
  let lo=0, hi=events.length;
  while (lo<hi) { const mid=(lo+hi)>>>1; if (events[mid][0]<=time) lo=mid+1; else hi=mid; }
  return events[lo-1] ?? null;
}
function signalStateAt(system,group,time) { return signalObservationAt(system,group,time)?.[1] ?? 'UNKNOWN'; }
function signalControlEvidence(link,lane,nextLink,time) {
  const records=typeof signalGeometry!=='undefined' ? signalGeometry.records :
    typeof sourceSignals!=='undefined' ? sourceSignals : [];
  return records.filter(row=>row.Link_ID===link).map(row=>{
    const lanes=Array.isArray(row.lane_ids) ? row.lane_ids : [],moves=Array.isArray(row.turning_moves) ? row.turning_moves : [];
    const laneScope=!lanes.length ? 'whole_link' : lane==null ? 'observed_lane_unknown' :
      lanes.includes(lane) ? 'observed_lane_matches' : 'different_native_lane';
    const movementScope=!moves.length ? 'all_recorded_turns' : nextLink==null ? 'observed_next_link_unknown' :
      moves.includes(nextLink) ? 'observed_turn_matches' : 'different_native_turn';
    const observation=signalObservationAt(row.system_id,row.group_id,time);
    return {system_id:row.system_id,group_id:row.group_id,signal_id:row.signal_id,Link_ID:row.Link_ID,
      lane_ids:lanes,turning_moves:moves,lane_scope:laneScope,movement_scope:movementScope,
      applies_to_observed_movement:laneScope==='different_native_lane' || movementScope==='different_native_turn' ? false :
        laneScope==='observed_lane_unknown' || movementScope==='observed_next_link_unknown' ? null : true,
      state:observation?.[1] ?? 'UNKNOWN',observation_time:observation?.[0] ?? null,
      source:'native_signal_scope_and_recorded_state',continuous_body_position_observed:false};
  });
}
function signalIcon(object,time) { return signalStateAt(object.system_id,object.group_id,time).toLowerCase(); }
let signalBand=null;
function signalFrameKey(time) {
  if(signalBand?.source===signalTimelines && time>=signalBand.from && time<signalBand.until)return signalBand.key;
  let from=-Infinity,until=Infinity;const states=[];
  for(const events of signalTimelines.values()) {
    let lo=0,hi=events.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(events[mid][0]<=time)lo=mid+1;else hi=mid;}
    if(lo)from=Math.max(from,events[lo-1][0]);if(lo<events.length)until=Math.min(until,events[lo][0]);
    states.push(events[lo-1]?.[1] || 'UNKNOWN');
  }
  signalBand={source:signalTimelines,from,until,key:states.join('|')};return signalBand.key;
}
let lastSignalTime = null,lastSignalSource = null,signalRenderRevision=0;
const continuousMode = Boolean(config.continuous);
const partialVisualPolicy=config.continuous?.visual_policy==='partial-native-v1' ? config.partial_visual_policy : null;
if(config.continuous?.visual_policy!=null && config.continuous.visual_policy!=='partial-native-v1' ||
   config.partial_visual_policy!=null && !partialVisualPolicy ||
   config.continuous?.visual_policy==='partial-native-v1' &&
   (!partialVisualPolicy || partialVisualPolicy.policy!=='partial-native-v1' ||
    partialVisualPolicy.pending_reason!=='reconstruction_pending' || partialVisualPolicy.body_position_available!==false ||
    partialVisualPolicy.native_status!=='completed' || partialVisualPolicy.native_validation!=='valid'))
  throw new Error('Contrato de visualizacion parcial incompatible');
function reportViewerError(error,source) {
  if(typeof reportError==='function')reportError(error,source);
  else console.error('[SimZ1 '+source+']',error);
}
const spatialRenderer = continuousMode && config.spatial_demand ?
  (typeof spatialView!=='undefined' ? spatialView : new SimZ1SpatialView(config.spatial_demand,config.continuous)) : null;
const visualLaneRenderer = continuousMode && typeof SimZ1VisualLanes === 'function' ?
  (typeof laneRenderer !== 'undefined' ? laneRenderer : new SimZ1VisualLanes(config.visual_lanes)) : null;
const certifiedQueueSettings=config.continuous?.checkpoint_settings ?? null;
let queueGapMeters=certifiedQueueSettings?.gap_m ?? (config.visual_lanes?.occupancy_corridors?.schema==='corridor-length-v1' ? .1 : 2);
let visualQueueRenderer=continuousMode && config.visual_lanes?.available && typeof SimZ1VisualQueues==='function' ?
  new SimZ1VisualQueues(visualLaneRenderer,certifiedQueueSettings ?? {gap_m:queueGapMeters},partialVisualPolicy?.policy ?? null) : null;
// The viewer owns one calendar-free day; source windows retain their native bounds.
const TIEMPO_INICIAL = continuousMode ? (config.temporal_policy ? config.continuous.start_seconds : 0) : config.replay_window?.start_seconds ?? config.time_horizon?.start_seconds ?? 0;
const TIEMPO_FINAL = continuousMode ? (config.temporal_policy || config.experimental_observation ? config.continuous.end_seconds : Math.min(config.continuous.end_seconds,86400)) : config.replay_window?.end_seconds ?? config.time_horizon?.end_seconds ?? 86400;
const INITIAL = TIEMPO_INICIAL, FINAL = TIEMPO_FINAL, SPEED = 120;
let clockFormat = continuousMode ? '24h' : '12h';
let continuousReplay = null, continuousPendingTime = null, continuousState = null;
const continuousPerformance={frames:[],transitions:[],lastFrameGapMs:0,maxFrameGapMs:0};
const renderCounters={markerCreates:0,markerReuses:0,labelBuilds:0,tripLayerUpdates:0,deckSubmissions:0,draws:0};
const selectionRequests={started:0,httpAttempts:0,retries503:0,completed:0,failed:0,aborted:0,stale:0,cacheHits:0,pending:0,samples:[]};
const featureWork={stopZoomCalls:0,stopLayerUpdates:0,stopZoomCpuMs:0,signalLayerUpdates:0,signalPropsCpuMs:0,
  signalViewCalls:0,signalViewUpdates:0,signalViewCpuMs:0};
let activePublicVehicleCount=0;
let maxDrawHz=60,lastDrawTimestamp=-Infinity,deckDrawStart=0,lastDeckDrawCpuMs=0;
let continuousWaitStart=null,lastAnimationTimestamp=null,firstWindowFrame=null;
let runHud = null, runHudRequest=null, runHudState = {status:'loading',data:null,error:null};
// Page windows are half-open. Keep the final paused frame strictly inside its
// interval, so a next-link entry at FINAL is not shown as a missing vehicle.
const LAST_REPLAY_INSTANT=config.pagination ? FINAL-Math.max(Number.EPSILON,Math.abs(FINAL)*Number.EPSILON*2) : FINAL;
let current = INITIAL, previous = null, paused = false, speed = SPEED;
const arrivalEffects=continuousMode && typeof SimZ1ArrivalEffects==='function' ? new SimZ1ArrivalEffects({
  identity:config.continuous,reducedMotion:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches===true}) : null;
let arrivalWindowCandidates=[],arrivalAnnotationsDrawn=false;
// No URL/config flag can enable fixture incidents. A native adapter does not
// exist yet; the manager reports rejected sidefiles without changing traffic.
const incidentEffects=continuousMode && typeof SimZ1IncidentEffects==='function' ?
  new SimZ1IncidentEffects({identity:config.continuous}) : null;
let emergencyAnnotations=[];
let timelines = new Map();
let laneTimelines = new Map();
for (const event of config.lane_replay?.events || []) {
  if (!laneTimelines.has(event.vehicle)) laneTimelines.set(event.vehicle, []);
  laneTimelines.get(event.vehicle).push(event);
}
// Stable order preserves native leave/enter order within the same QSim step.
for (const events of laneTimelines.values()) events.sort((a,b) => a.time-b.time);
function laneObservationAt(vehicle, link, time, inclusive=true, source=laneTimelines) {
  const events = source.get(vehicle) || [];
  let lo = 0, hi = events.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (events[mid].time < time || inclusive && events[mid].time === time) lo = mid+1; else hi = mid; }
  const event = events[lo-1] || null;
  const lane = event?.type === 'entered lane' && event.link === link ? event.lane : null;
  return {lane,event,observed_at:time};
}
let incidents = incidentRecords;
let incidentKey = null;
function incidentActive(incident,time) { return incident.start <= time && (incident.end == null || time < incident.end); }
for (const segment of replaySegments) {
  if (!timelines.has(segment.vehicle)) timelines.set(segment.vehicle, []);
  timelines.get(segment.vehicle).push(segment);
}
// The exported array contains link segments; count only unique vehicle keys.
const trajectoriesByVehicle = Object.fromEntries(timelines);
const totalVehicleCount = continuousMode ?
  (config.continuous.total_reconstructed_vehicles ?? config.hud?.reconstructed_vehicles ?? Object.keys(trajectoriesByVehicle).length) :
  Object.keys(trajectoriesByVehicle).length;
for (const records of timelines.values()) {
  records.sort((a,b) => a.timestamps[0]-b.timestamps[0]);
  let tripKey = null, maximum = null;
  for (const record of records) {
    const key = record.Agent_ID + ':' + record.Trip?.Departure;
    if (key !== tripKey) { maximum = null; tripKey = key; }
    if (Number.isFinite(record.Speed_kmh)) maximum = maximum == null ? record.Speed_kmh : Math.max(maximum,record.Speed_kmh);
    // A paged record already carries the maximum from its complete journey.
    // Recomputing from the loaded time window would erase earlier evidence.
    if ((!config.pagination && !continuousMode) || !Object.prototype.hasOwnProperty.call(record,'Max_Speed_kmh')) record.Max_Speed_kmh = maximum;
  }
}
function activeSegment(vehicle, time) {
  const records = timelines.get(vehicle) || [];
  let lo = 0, hi = records.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (records[mid].timestamps[0] <= time) lo = mid+1; else hi = mid; }
  const active=records.slice(0,lo).filter(record=>time<record.timestamps[1]);
  return active.length===1 ? active[0] : null; // Zero-duration evidence cannot hide a positive interval.
}
// Centered interval index: queries inspect active intervals rather than every
// vehicle in the population. Arbitrary forward/backward seeks use the same index.
function buildIntervalIndex(records) {
  if (!records.length) return null;
  const sorted=records.filter(r=>r.timestamps[1]>r.timestamps[0]).sort((a,b)=>a.timestamps[0]-b.timestamps[0]);
  if (!sorted.length) return null;
  const center=sorted[sorted.length>>>1].timestamps[0], left=[],right=[],cross=[];
  for (const record of sorted) {
    if (record.timestamps[1]<=center) left.push(record);
    else if(record.timestamps[0]>center) right.push(record);
    else cross.push(record);
  }
  return {center,byStart:cross,byEnd:[...cross].sort((a,b)=>b.timestamps[1]-a.timestamps[1]),
    left:buildIntervalIndex(left),right:buildIntervalIndex(right)};
}
let intervalIndex=buildIntervalIndex(replaySegments);
function activeRecordsAt(time, node=intervalIndex, result=[]) {
  if (!node) return result;
  if(time<node.center) {
    for(const record of node.byStart){if(record.timestamps[0]>time)break;result.push(record);}
    return activeRecordsAt(time,node.left,result);
  }
  for(const record of node.byEnd){if(record.timestamps[1]<=time)break;result.push(record);}
  return activeRecordsAt(time,node.right,result);
}
const uiShell = document.createElement('div');
uiShell.id = 'simz1-ui';
document.body.appendChild(uiShell);
const hud = document.createElement('section');
hud.id = 'simz1-controls';
hud.setAttribute('aria-label','Controles de simulacion');
const clock = document.createElement('div');
clock.id = 'simz1-clock';
const totalAgents = document.createElement('div');
totalAgents.id = 'simz1-run-summary';
totalAgents.textContent = continuousMode ? '' : 'Vehiculos: ' + totalVehicleCount.toLocaleString('en-US');
const technicalHelp = document.createElement('details');
technicalHelp.id = 'simz1-help';
technicalHelp.open = false;
const technicalSummary = document.createElement('summary');
technicalSummary.textContent = 'Ayuda';
technicalSummary.setAttribute('aria-label','Ayuda y datos de la corrida');
const technicalHelpContent = document.createElement('div');
technicalHelpContent.id = 'simz1-help-content';
const technicalStats = document.createElement('pre');
technicalStats.textContent = continuousMode ? '' : 'Vehiculos reconstruidos: ' + totalVehicleCount.toLocaleString('en-US');
const metadata = config.hud || {};
if (metadata.run_id && !continuousMode) {
  technicalStats.textContent += '\nPersonas planificadas: ' + metadata.planned_persons +
    ' | Viajes planificados: ' + metadata.planned_trips +
    '\nSalidas registradas (etapas): ' + metadata.observed_departures +
    '\nCorrida: ' + metadata.run_id + '\nSemilla demanda: ' + metadata.demand_seed +
    ' | MATSim: ' + metadata.matsim_seed + ' | Iteracion: ' + metadata.iteration;
}
if (config.lane_replay && !continuousMode) {
  const configuredLanes = config.lane_replay.use_lanes;
  technicalStats.textContent += '\nCarriles configurados: ' + (configuredLanes == null ? 'no disponible' :
    configuredLanes ? 'activados' : 'desactivados') +
    '\nEventos de cola registrados (muestra): ' + config.lane_replay.event_count +
    ' | Vehiculos con eventos: ' + config.lane_replay.vehicles_with_events;
}
if (metadata.priority) {
  technicalStats.textContent += '\nPrioridad sin semaforo: ' + (metadata.priority.enabled ? 'activada' : 'desactivada') +
    ' | Parada en cabecera: ' + metadata.priority.stop_seconds + ' s' +
    '\nClasificacion: ' + metadata.priority.classification + ' | Conflictos: ' + metadata.priority.conflicts;
}
if (config.trajectory_stats && !continuousMode) {
  technicalStats.textContent += '\nPersonas en eventos: '+config.trajectory_stats.observed_persons+
    ' | Vehiculos sin intervalo cerrado de duracion positiva: '+config.trajectory_stats.vehicles_without_drawable_segments+
    ' | Excluidos por muestreo: '+config.trajectory_stats.unsampled_vehicles;
}
if (config.pagination) {
  const page=config.pagination;
  totalAgents.textContent = totalAgents.textContent.replace('Vehiculos: ','Vehiculos en bloque: ') +
    ' | Total replay: '+page.total_reconstructed_vehicles.toLocaleString('en-US');
  technicalStats.textContent += '\nReplay por bloques, sin muestreo: 100 %' +
    '\nVehiculos reconstruidos en toda la corrida: '+page.total_reconstructed_vehicles.toLocaleString('en-US')+
    '\nTramos en este bloque: '+page.loaded_segments.toLocaleString('en-US')+
    ' | Tramos en toda la corrida: '+page.total_segments.toLocaleString('en-US');
  if (page.visual_vehicle_counts) {
    technicalStats.textContent += '\nVehiculos con al menos un intervalo visual representable: '+page.visual_vehicle_counts.with_representable_interval.toLocaleString('en-US')+
      '\nVehiculos reconstruidos sin intervalo visual representable: '+page.visual_vehicle_counts.without_representable_interval.toLocaleString('en-US')+
      '\nVehiculos con todos sus planes visuales no disponibles: '+page.visual_vehicle_counts.only_unavailable_motion_plans.toLocaleString('en-US');
  }
}
if (config.operational_counts && !continuousMode) {
  for (const [key,label] of [['completed_legs','Llegadas completadas en el archivo validado'],['pending_legs_at_horizon','Pendientes al cierre de eventos'],
    ['aborted_before_horizon','Abortados antes del horizonte'],['unstarted_legs','Sin iniciar']]) {
    if (Number.isFinite(config.operational_counts[key])) technicalStats.textContent += '\n'+label+': '+config.operational_counts[key].toLocaleString('en-US');
  }
}
if (config.selection_warning) {
  const warning = document.createElement('div');
  warning.setAttribute('role', 'alert');
  warning.className = 'simz1-warning';
  warning.textContent = config.selection_warning;
  hud.append(warning);
}
const toggle = document.createElement('button');
toggle.textContent = 'Pausar';
const legend = document.createElement('div');
legend.id = 'simz1-speed-legend';
legend.innerHTML = '<span style="color:#28d25f">Verde &gt;40 km/h</span> | <span style="color:#ffd228">Amarillo 15–40 km/h</span> | <span style="color:#f54141">Rojo &lt;15 km/h</span> | <span style="color:#fff">Blanco = 0 km/h</span>';
if (continuousMode) legend.innerHTML = '<span style="color:#28d25f">Verde &gt;40</span> | <span style="color:#ffd228">Amarillo 15–40</span> | <span style="color:#f54141">Rojo &lt;15</span> | <span style="color:#fff">Blanco = 0 km/h</span>';
technicalHelpContent.innerHTML = 'Semaforos: estados nativos por sistema/grupo; ? = desconocido sin evento previo.<br>Blanco: detenido (tolerancia numerica de 0.0001 km/h) | Color: velocidad visual estimada | Sin estelas.';
technicalHelpContent.innerHTML += '<br>Triangulo con vehiculos: incidente registrado activo.';
if(continuousMode)technicalHelpContent.innerHTML += '<br>Incidentes por participantes: adaptador nativo no instalado; fixtures de dise\u00f1o, FORCE y solapamientos no activan naranja ni emergencias.';
if(continuousMode && typeof transitStops!=='undefined') {
  const stopNote=document.createElement('p');
  stopNote.textContent='Paradas: pictograma de bus verde = Transmetro; azul = TuBus, Transurbano, urbanos y extraurbanos verificados. '+
    'La doble flecha indica transbordo documentado; las placas apiladas agrupan paradas al alejarse. '+
    'Son referencias del catálogo: el tooltip distingue fuentes, operador, sentidos y uso en la simulación. '+
    (transitStops.records.length ? transitStops.records.length+' paradas con evidencia; no implican buses activos ni carriles asignados.' :
      'Sin paradas habilitadas para dibujar: consulte getStopDiagnostics() para ver los datos pendientes.');
  technicalHelpContent.append(stopNote);
}
if (!config.signal_replay?.event_count) technicalHelpContent.innerHTML += '<br>Sin eventos semaforicos nativos disponibles: no se calculan fases ilustrativas.';
if(continuousMode)technicalHelpContent.innerHTML +=
  '<br>Circulos de llegada: anotaciones durante cinco segundos reales, incluso en pausa; no cuentan como vehiculos activos.';
if(continuousMode && typeof signalGeometry!=='undefined')technicalHelpContent.innerHTML +=
  '<br>Semaforos: cuerpo vertical y luces circulares; la cara superior repite el estado para la vista cenital.'+
  '<br>Desde lejos: un acceso representativo por interseccion. Acerque la camara para ver todos los accesos o pase el cursor para consultar sus estados.';
if(!continuousMode)technicalHelpContent.innerHTML += '<br>Semaforos por enlace entrante: horizontales girados 90 grados.';
const seeker = document.createElement('input');
seeker.type = 'range'; seeker.min = INITIAL; seeker.max = FINAL; seeker.step = 1;
seeker.setAttribute('aria-label', 'Hora de simulacion dentro del horizonte de la corrida');
seeker.id = 'simz1-time-slider';
const controls = document.createElement('div');
controls.className = 'simz1-buttons';
const realtime = document.createElement('button');
realtime.textContent = '1x';
realtime.title = 'Tiempo real (1x)';
const original = document.createElement('button');
original.textContent = '120x';
original.title = 'Reproduccion acelerada (120x)';
controls.append(toggle,realtime,original);
let clockFormatButton=null;
if (continuousMode) {
  clockFormatButton=document.createElement('button');clockFormatButton.id='simz1-clock-format';
  clockFormatButton.textContent='12 h';clockFormatButton.title='Cambiar reloj a formato de 12 horas';
  clockFormatButton.onclick=()=>setClockFormat(clockFormat==='24h' ? '12h' : '24h');
  controls.append(clockFormatButton);
  const backward=document.createElement('button');backward.textContent='−60 s';
  backward.title='Retroceder un minuto conservando el agente seleccionado';
  backward.onclick=()=>requestContinuousTime(Math.max(INITIAL,current-60),true);
  controls.append(backward);
  for(const [delta,label] of [[-3600,'-1 h'],[3600,'+1 h']]) {
    const step=document.createElement('button');step.textContent=label;
    step.onclick=()=>requestContinuousTime(Math.max(INITIAL,Math.min(FINAL,current+delta)),true);
    controls.append(step);
  }
}
const typeFilter=document.createElement('select');typeFilter.id='simz1-type-filter';
typeFilter.setAttribute('aria-label','Mostrar tipo de vehiculo');
for(const [value,label] of [['all','Todos los tipos'],['private','Particulares'],['car','Carros'],['motorcycle','Motos'],['freight','Carga'],['bus','Buses']]) {
  const option=document.createElement('option');option.value=value;option.textContent=label;typeFilter.append(option);
}
typeFilter.value='all';
const routeFilter=document.createElement('input');routeFilter.id='simz1-route-filter';routeFilter.type='text';
routeFilter.value='';routeFilter.placeholder='ID de ruta (opcional)';routeFilter.setAttribute('aria-label','Filtrar ID exacto de ruta de bus o carga');
const filterStatus=document.createElement('span');filterStatus.textContent='Sin filtros';
function visibleByUserChoice(marker) {
  const family=marker.Visual_Vehicle_Presentation?.family ??
    (typeof SimZ1VehicleCatalog==='function' ? SimZ1VehicleCatalog.resolve(marker).family : marker.Vehicle_Family);
  const kind=marker.Trip?.Transit ? 'bus' : marker.Trip?.Freight || family==='truck' ? 'freight' : family;
  const route=marker.Trip?.Transit?.route_id ?? marker.Trip?.Freight?.route_id;
  return (typeFilter.value==='all' || typeFilter.value===kind || typeFilter.value==='private' && ['car','motorcycle'].includes(kind)) &&
    (!routeFilter.value.trim() || route===routeFilter.value.trim());
}
typeFilter.onchange=routeFilter.onchange=()=>{lastMarkerTime=null;render();};
controls.append(typeFilter,routeFilter,filterStatus);
const toolbar = document.createElement('div');
toolbar.className = 'simz1-toolbar';
toolbar.append(clock,controls);
technicalHelpContent.innerHTML += '<br>Clic: recorrido celeste oscuro, futuro celeste claro y O-D durante el viaje activo.<br>Futuro del replay registrado, no prediccion. Clic al fondo o fuera del mapa: limpiar.';
technicalHelpContent.innerHTML += '<br>Origen: circulo blanco. Destino: bandera de meta.';
technicalHelpContent.innerHTML += '<br>Movimiento estimado con limites de enlace/vehiculo; espera residual de causa desconocida salvo evidencia nativa.';
technicalHelpContent.innerHTML += '<br>Aceleracion y frenado interpolados entre eventos; no son velocidades instantaneas medidas por MATSim.';
technicalHelpContent.innerHTML += '<br>Datos insuficientes: interpolacion durante todo el intervalo, sin agregar espera.';
technicalHelpContent.innerHTML += '<br>Intervalo incompatible con los limites: sin marcador ni tramo inventado. Gris: velocidad desconocida.';
technicalHelpContent.innerHTML += '<br>QSim con carriles: colas, sin cambio lateral ni car-following continuo.';
technicalHelpContent.innerHTML += visualLaneRenderer && config.visual_lanes?.available ?
  '<br>Carriles: cantidad efectiva por sentido. ID nativo cuando identifica un carril; en otro caso asignacion visual determinista estimada.'+
  '<br>Desplazamiento lateral metrico estimado; ancho nominal si no existe ancho validado. Geometria aproximada de la red, no limites medidos de calzada.'+
  '<br>Offsets paralelos; pose estimada continua solo entre enlaces observados compatibles. La ruta seleccionada permanece sobre el eje.' :
  '<br>Posicion dibujada: eje interpolado; posicion lateral no observada.';
if(continuousMode && config.visual_lanes?.available) technicalHelpContent.innerHTML +=
  '<br>Una nueva pertenencia nativa puede corregir la asignacion visual; esa correccion no es una maniobra lateral observada.';
if(continuousMode && config.visual_lanes?.reason) {
  const laneWarning=document.createElement('div');
  laneWarning.textContent='Carriles visuales no disponibles: '+config.visual_lanes.reason;
  technicalHelpContent.append(laneWarning);
}
if (config.demand_window) {
  technicalHelpContent.innerHTML += '<br>Demanda planificada: [' + formatDuration(config.demand_window.start_seconds) + ', ' +
    formatDuration(config.demand_window.end_seconds) + ') desde el origen tecnico; pesos sinteticos, no aforos.';
  technicalHelpContent.innerHTML += '<br>Simulacion hasta ' + (continuousMode ? config.time_horizon.end_seconds+' s (fuente)' : formatDuration(config.time_horizon.end_seconds)) +
    '; replay hasta ' + formatDuration(TIEMPO_FINAL) + '. El deslizador no genera viajes.';
}
if (config.lane_replay?.event_count) {
  technicalHelpContent.innerHTML += '<br>ID de cola y tiempos registrados; no son trayectorias de rebase.';
} else {
  technicalHelpContent.innerHTML += visualLaneRenderer && config.visual_lanes?.available ?
    '<br>Sin eventos de carril disponibles: asignacion visual estimada, sin pertenencia nativa.' :
    '<br>Sin eventos de carril disponibles: no se asignan carriles visuales.';
}
technicalHelp.append(technicalSummary,technicalHelpContent,technicalStats);
hud.append(toolbar,seeker,legend);
if (!continuousMode) hud.append(totalAgents);
hud.append(technicalHelp);
if (config.pagination) {
  const page=config.pagination;
  const navigation=document.createElement('div');navigation.className='simz1-block-navigation';
  const index=document.createElement('a');index.href=page.index_url;index.textContent='Indice';
  const label=document.createElement('label');label.textContent='Bloque '+(page.block_index+1)+'/'+page.block_count+' ';
  const chooseBlock=document.createElement('select');chooseBlock.setAttribute('aria-label','Cambiar bloque temporal del mismo replay');
  for (const block of page.blocks) {
    const option=document.createElement('option');option.value=block.url;
    option.textContent=(block.index+1)+': '+formatDuration(block.start_seconds)+'–'+formatDuration(block.end_seconds);
    option.selected=block.index===page.block_index;chooseBlock.append(option);
  }
  chooseBlock.onchange=()=>{window.location.href=chooseBlock.value;};
  label.append(chooseBlock);navigation.append(index,label);
  for (const [offset,text] of [[-1,'Anterior'],[1,'Siguiente']]) {
    const block=page.blocks[page.block_index+offset];
    if (block) { const link=document.createElement('a');link.href=block.url;link.textContent=text;navigation.append(link); }
  }
  hud.append(navigation);
  technicalHelpContent.innerHTML += '<br>Bloques temporales sin muestreo: el reloj muestra solo el bloque cargado. Cambiar de bloque libera sus tramos.'+
    '<br>El borde final es exclusivo: la reproduccion se pausa antes del siguiente bloque. Use Siguiente o el selector para continuar.'+
    '<br>Activos visibles cuenta marcadores con posicion representable; no es el total de vehiculos activos en QSim.'+
    '<br>Los tiempos, llegadas y fases no se recortan. El historial y futuro completos se consultan al seleccionar un viaje, mediante el servidor local.'+
    '<br>Mientras se consulta, no se presenta el historial parcial del bloque como si fuera el recorrido completo.';
}
if (continuousMode) {
  technicalStats.textContent='Totales pendientes de validar. Dibujados cuenta marcadores enviados al mapa después de los filtros, no personas generadas ni activos QSim.';
  technicalHelpContent.innerHTML += (config.temporal_policy ? '<br>Reproduccion continua de calentamiento, jornada, demanda posterior y drenaje; sin reinicio en medianoche. Las ventanas se cargan automaticamente con cache limitada.' : '<br>Reproduccion continua de 00:00:00 a 24:00:00; el ultimo tick cierra el dia. Las ventanas se cargan automaticamente con cache limitada.')+
    '<br>La carga pausa el reloj sin omitir tiempo. La camara y el viaje seleccionado se conservan al cargar otra ventana.'+
    '<br>Las rutas fuente se consultan al seleccionar un agente; se dibuja solo la parte observada en esta jornada.'+
    '<br>Sin llegada observada hasta el fin de observacion: viaje censurado, sin inventar una llegada.';
  if(spatialRenderer)technicalHelpContent.innerHTML += '<br>Dominio espacial validado: solo el tramo modelado dentro de Z1. Zonas exteriores son etiquetas OD sinteticas, sin coordenadas ni trayectos exteriores.'+
    '<br>Puerta a puerta: N/D. Las marcas de origen y llegada representan posiciones nativas dentro del dominio, nunca destinos exteriores supuestos.';
  const coverage=config.continuous.source_replay_window || config.continuous;
  if(coverage.start_seconds>INITIAL || coverage.end_seconds<FINAL)
    technicalHelpContent.innerHTML += '<br>Fuente parcial: '+coverage.start_seconds+'..'+coverage.end_seconds+
      ' s. Fuera de ese intervalo no hay evidencia disponible; el reloj conserva el horizonte 0..'+FINAL+' s.';
  if(visualQueueRenderer) {
    technicalHelpContent.innerHTML += '<br>Colas: espaciado inferido con espera de extremo respaldada; orden por entrada nativa al carril si esta disponible, o entrada al enlace como respaldo estimado. Linea de alto aproximada desde el extremo del enlace.'+
      '<br>Cuerpos rígidos por familia: dimensiones registradas con procedencia o supuestos explícitos del catálogo visual; sin cambiar PCU ni capacidad QSim.'+
      '<br>La cola conserva el margen hasta la salida registrada; no se adelanta la liberacion dentro de una fase detenida. El cambio discreto de enlace no aporta una trayectoria subpaso medida.'+
      '<br>El color conserva la velocidad del plan interpolado; el ajuste grafico de espaciado no es una nueva velocidad fisica.'+
      '<br>Envolvente de seguridad: longitud del cuerpo + gap; margen lateral de 0.10 m por lado. No cambia la carroceria, la seleccion ni QSim.'+
      '<br>Omisiones y conflictos: disponibles por vehicle_id aqui y en simz1Continuous.getVisualDiagnostics(). Un conflicto de eventos sin solucion geometrica permanece explicito.'+
      '<br>El limite de almacenamiento mostrado es geometrico visual; no es una medicion de ocupacion ni capacidad QSim.'+
      '<br>Selección: contorno del cuerpo y tolerancia adicional de 8 px (mouse) o 18 px (touch), sin ampliar dimensiones métricas.';
    const gapLabel=document.createElement('label'),gapInput=document.createElement('input');
    gapLabel.textContent='Espacio visual entre autos (m): ';
    gapInput.id='simz1-queue-gap';gapInput.type='number';gapInput.min=.1;gapInput.max=10;gapInput.step=.1;gapInput.value=queueGapMeters;
    if(certifiedQueueSettings){gapInput.disabled=true;gapInput.title='Esta reconstruccion fue verificada con estos margenes. Otros valores requieren preparar nuevamente su soporte.';}
    gapInput.setAttribute('aria-label','Espacio visual entre autos en metros');
    gapInput.onchange=()=>{const value=Number(gapInput.value);
      if(Number.isFinite(value) && value>=.1 && value<=10)setQueueGap(value);
      gapInput.value=queueGapMeters;};
    gapLabel.append(gapInput);technicalHelpContent.append(gapLabel);
  }
  const mapNote=document.createElement('div');
  mapNote.textContent='Nombres OSM: hasta dos etiquetas por via; ocultos con zoom menor a 15. Referencias: desde zoom 16. '+
    (config.visual_lanes?.landmarks_note || 'Sin referencias de lugares verificables disponibles.');
  technicalHelpContent.append(mapNote);
}
uiShell.append(hud);
let partialVisualStatus=null;
if(partialVisualPolicy) {
  partialVisualStatus=document.createElement('p');partialVisualStatus.id='simz1-partial-visual-status';
  partialVisualStatus.textContent='Vista parcial: algunos vehículos no tienen posición verificable y pueden no aparecer.';
  technicalHelpContent.append(partialVisualStatus);
}
// Hide the existing DOM, never recreate controls or change replay/camera state.
let hideBar=null,showBar=null;
if (continuousMode) {
  const preferenceKey='simz1.controls.hidden';
  hideBar=document.createElement('button');showBar=document.createElement('button');
  hideBar.id='simz1-hide-bar';showBar.id='simz1-show-bar';
  for (const [button,label] of [[hideBar,'Ocultar barra'],[showBar,'Mostrar barra']]) {
    button.type='button';button.textContent=label;
    button.setAttribute('aria-label',label);button.setAttribute('aria-controls',hud.id);
  }
  function setBarHidden(hidden,remember=false) {
    hud.hidden=hidden;showBar.hidden=!hidden;
    for(const button of [hideBar,showBar])button.setAttribute('aria-expanded',String(!hidden));
    if(remember) {
      try { window.sessionStorage.setItem(preferenceKey,String(hidden)); } catch (_) { /* Session storage may be unavailable. */ }
      (hidden ? showBar : hideBar).focus();
    }
  }
  hideBar.onclick=()=>setBarHidden(true,true);
  showBar.onclick=()=>setBarHidden(false,true);
  controls.append(hideBar);uiShell.append(showBar);
  let hidden=false;
  try { hidden=window.sessionStorage.getItem(preferenceKey)==='true'; } catch (_) { /* Visible by default. */ }
  setBarHidden(hidden);
}
const runPanel = continuousMode ? document.createElement('section') : null;
const runFields = new Map();
let runScope=null,runError=null,runErrorDetail=null,runRetry=null,queueStatus=null,populationLabel=null,publicFleetLabel=null,freightFleetLabel=null,runIdentityLabel=null,cohortLabel=null,cameraCountsLabel=null;
if (runPanel) {
  runPanel.id='simz1-run-panel';runPanel.setAttribute('aria-label','Vehículos configurados');
  const populationValue=document.createElement('span');
  populationLabel=document.createElement('span');populationLabel.textContent='Vehículos particulares: ';
  populationValue.id='simz1-count-private_vehicles';populationValue.textContent='—';
  runFields.set('private_vehicles',populationValue);
  runPanel.append(populationLabel,populationValue);
  if(config.temporal_policy) {
    cohortLabel=document.createElement('div');cohortLabel.id='simz1-cohort-totals';technicalHelp.append(cohortLabel);
  }
  cameraCountsLabel=document.createElement('div');cameraCountsLabel.id='simz1-camera-counts';technicalHelp.append(cameraCountsLabel);
  publicFleetLabel=document.createElement('span');publicFleetLabel.id='simz1-fixed-public-fleet';
  publicFleetLabel.textContent=' · Transporte público: —';runPanel.append(publicFleetLabel);
  freightFleetLabel=document.createElement('span');freightFleetLabel.id='simz1-fixed-freight-fleet';
  freightFleetLabel.textContent=' · Camiones: —';runPanel.append(freightFleetLabel);
  runIdentityLabel=document.createElement('div');runIdentityLabel.id='simz1-served-identity';
  runIdentityLabel.textContent='Validando corrida e iteración…';technicalHelp.append(runIdentityLabel);
  const rows=document.createElement('dl');rows.id='simz1-technical-totals';
  for (const [key,label] of [['persons_generated','Personas particulares registradas (dato histórico)'],['planned_trips','Viajes planificados'],
    ['completed_trips','Completados'],['pending_censored_trips','Pendientes/censurados'],
    ['reconstructed_vehicles','Vehículos reconstruidos'],['run_id','Corrida'],['iteration','Iteración']]) {
    const term=document.createElement('dt'),value=document.createElement('dd');
    term.textContent=label;value.id='simz1-count-'+key;value.textContent='—';
    rows.append(term,value);runFields.set(key,value);
  }
  runScope=document.createElement('div');runScope.id='simz1-run-scope';
  runError=document.createElement('div');runError.id='simz1-run-error';runError.setAttribute('role','status');
  runErrorDetail=document.createElement('pre');runErrorDetail.id='simz1-run-error-detail';runErrorDetail.hidden=true;
  runErrorDetail.style.whiteSpace='pre-wrap';
  runRetry=document.createElement('button');runRetry.id='simz1-run-retry';runRetry.textContent='Reintentar totales';
  runRetry.hidden=true;runRetry.onclick=()=>loadRunHud();
  technicalHelp.append(runErrorDetail,rows,runScope);hud.append(runError,runRetry);uiShell.append(runPanel);
  if(visualQueueRenderer) {
    queueStatus=document.createElement('div');queueStatus.id='simz1-queue-status';queueStatus.setAttribute('role','status');
    technicalHelp.append(queueStatus);
    const vehicleInput=document.createElement('input'),inspectButton=document.createElement('button'),result=document.createElement('pre');
    vehicleInput.setAttribute('aria-label','vehicle_id para diagnostico tecnico');vehicleInput.placeholder='vehicle_id';
    inspectButton.textContent='Diagnosticar vehiculo';result.style.whiteSpace='pre-wrap';
    inspectButton.onclick=()=>{result.textContent=JSON.stringify(diagnoseVehicle(vehicleInput.value),null,2);};
    technicalHelp.append(vehicleInput,inspectButton,result);
  }
}
function renderRunHud() {
  const data=runHudState.status==='ready' ? runHudState.data : null;
  // Called on metadata transitions only, never by the animation loop.
  // Clear first so a presentation/validation error cannot leave previous totals.
  runFields.get('private_vehicles').textContent='—';
  publicFleetLabel.textContent=' · Transporte público: —';
  freightFleetLabel.textContent=' · Camiones: —';
  const vehicles=SimZ1ContinuousHud.vehicleSummary(data);
  if(runIdentityLabel) {
    runIdentityLabel.textContent=data ? 'Corrida: '+data.run_id+' · Iteración '+data.iteration : 'Corrida e iteración pendientes de validación';
    runIdentityLabel.title=data ? 'Fuente: '+(data.source_version || config.continuous.source_version || 'histórica') : '';
  }
  if(cohortLabel)cohortLabel.textContent=data?.counts.principal_cohort_persons!=null ?
    'Personas de cohorte principal (dato histórico): '+data.counts.principal_cohort_persons+' · Contexto: '+data.counts.context_persons+
    ' (previo '+data.counts.warmup_context_persons+', posterior '+data.counts.post_context_persons+') · Jornada '+
    config.temporal_policy.study_date+' · America/Guatemala' : '';
  for (const [key,node] of runFields) {
    const value=key==='private_vehicles' ? vehicles.private_vehicles :
      key==='run_id' || key==='iteration' ? data?.[key] : data?.counts[key];
    node.textContent=value==null ? '—' : String(value);
  }
  const publicConfig=data?.public_transport?.configured;
  publicFleetLabel.textContent=' · Transporte público: '+(vehicles.public_vehicles ?? '—');
  runError.textContent=runHudState.status==='error' ? 'Totales no disponibles. Detalle técnico en Ayuda.' :
    (runHudState.status==='loading' ? 'Validando totales…' : '');
  runError.hidden=!runError.textContent;
  runErrorDetail.textContent=runHudState.error ? 'Error de totales\n'+(runHudState.error_details || runHudState.error) : '';
  runErrorDetail.hidden=!runErrorDetail.textContent;
  const freight=data?.freight_transport;
  freightFleetLabel.textContent=' · Camiones: '+(freight?.configured?.enabled===false ? 0 :
    (freight?.configured?.vehicles_configured ?? '—'));
  runRetry.hidden=runHudState.status!=='error';
  runRetry.disabled=runHudState.status==='loading';
  runScope.textContent='';
  technicalStats.textContent='Dibujados: marcadores con posición representable enviados al mapa después de los filtros; incluye los que quedan fuera de cámara. '+
    'No mide oclusión, flota configurada ni activos QSim. Los pictogramas de paradas son referencias fijas y no cuentan como vehículos. '+
    'Particulares cuenta vehículos privados únicos de la cohorte principal con política temporal; en otro caso, particulares configurados. '+
    'Solo se muestra cuando el XML verificado acredita una asignación uno a uno. — significa evidencia ausente. '+
    'B cuenta la flota pública única configurada: no suma expediciones ni buses visibles. Activos QSim: no disponibles (sin serie validada). '+
    'La carga se desglosa abajo: no se suma al contador de particulares, pero sí al N no público cuando la corrida usa composición. Los buses y sus conductores quedan fuera de N.';
  if (data) {
    const source=data.source_time_horizon,metrics=data.metrics_window;
    runScope.textContent='Indicadores fuente: '+(source.end_seconds-source.start_seconds)/3600+' h; observados '+
      metrics.start_seconds+'..'+metrics.end_seconds+' s. Vista: '+INITIAL+'..'+FINAL+' s.';
    if(config.experimental_observation)runScope.textContent+=config.experimental_observation.policy==='fixed-day-24h-v1' ?
      ' Demanda y observacion 00-24 h. Pendientes censurados; no son llegadas. Camiones y buses sin umbral privado de una hora.' :
      ' Demanda 00-24 h; seguimiento historico 24-30 h. Indicador de carga: una hora tras el cierre de su ventana original.';
    if(data.day_observation)technicalStats.textContent+='\nCorte diario: '+JSON.stringify(data.day_observation.counts)+
      '\nPendientes: '+JSON.stringify(data.day_observation.pending_classifications);
    if(data.screening)runScope.textContent+=' Screening: '+data.screening.status+
      ((data.screening.reasons || []).length ? ' ('+data.screening.reasons.join(', ')+')' : '');
    if(metrics.start_seconds!==INITIAL || metrics.end_seconds!==FINAL)
      runScope.textContent+=config.temporal_policy ? ' Totales particulares con contexto; el analisis separa la cohorte principal.' : ' Completados y pendientes no recalculados a 24 h.';
    technicalStats.textContent+='\nVehículos con eventos: '+(data.counts.vehicles_with_events ?? 'No disponible')+
      '\nSemilla demanda: '+(data.run_details?.demand_seed ?? '—')+' · MATSim: '+(data.run_details?.matsim_seed ?? '—')+
      '\nFecha: '+(data.run_details?.study_date ?? data.run_details?.public_service_date ?? '—')+
      '\nFuente: '+(data.source_version ?? '—')+' · Manifiesto: '+data.run_manifest_sha256+
      '\nProcedencia N: '+(data.vehicle_summary?.private_basis ?? 'sin evidencia histórica de equivalencia')+
      '\nProcedencia B: '+(data.vehicle_summary?.public_basis ?? 'sin IDs únicos verificados')+
      '\nTransmetro: '+(publicConfig?.fleet_by_system?.transmetro ?? '—')+' · TuBus: '+(publicConfig?.fleet_by_system?.tubus ?? '—')+
      '\nExpediciones públicas programadas: '+(publicConfig?.public_transport_departures_scheduled ?? '—')+
      ' · Observadas: '+(data.public_transport?.observed?.observed_expedition_starts ?? '—')+
      '\nTransporte pesado: '+(freight?.configured?.enabled===false ? 'desactivado' :
        (freight?.configured?.vehicles_configured ?? '—')+' configurados / '+(freight?.observed?.vehicles_observed ?? '—')+
        ' incorporados · '+(freight?.configured?.departures_scheduled ?? '—')+' expediciones programadas / '+
        (freight?.observed?.departures_observed ?? '—')+' salidas observadas')+
      (freight?.observed?.day_observation_policy==='fixed-day-24h-v1' ?
        '\nCarga al corte diario: '+freight.observed.arrivals_observed+' llegadas · '+
        freight.observed.active_in_traffic_at_cut+' activos · '+freight.observed.waiting_for_insertion+' esperando incorporación · '+
        freight.observed.scheduled_not_departed_at_cut+' sin salida observada · '+freight.observed.censored_at_horizon+' censurados' : '')+
      '\n'+runScope.textContent;
    if(config.temporal_policy)technicalStats.textContent+='\n'+[
      ['warmup','Calentamiento'],['study','Jornada principal'],['post_demand','Contexto posterior'],['drain','Drenaje']]
      .filter(([key])=>config.temporal_policy.windows?.[key])
      .map(([key,label])=>{const window=config.temporal_policy.windows[key];return label+': '+window.start_seconds+'..'+window.end_seconds+' s';}).join('\n');
  }
}
function loadRunHud() {
  // Only one metadata request per viewer. The controller validates the immutable
  // run/manifest/iteration/source identity before accepting its response.
  if(runHudRequest)return runHudRequest;
  let request;
  try { request=runHud.load(); }
  catch(error) { setRunHudFailure(error,'carga de totales');return Promise.resolve(runHudState); }
  runHudRequest=Promise.resolve(request).then(()=>runHudState).catch(error=>{
    setRunHudFailure(error,'carga de totales');return runHudState;
  }).finally(()=>{runHudRequest=null;});
  return runHudRequest;
}
function setRunHudFailure(error,source) {
  const message=error?.message || String(error);
  runHudState={status:'error',data:null,error:message,error_details:source+'\n'+(error?.stack || message)};
  // A metadata failure has one owner. Never copy it into the map's error log,
  // where it would remain after a successful retry and duplicate this detail.
  try { renderRunHud(); }
  catch(presentationError) {
    // If even the dedicated error panel fails, retain the failure in the map's
    // independent diagnostic log without preventing its initialization/playback.
    reportViewerError(new Error('No se pudo presentar el detalle de totales: '+message,
      {cause:presentationError}),'panel de totales');
  }
}
function updateRunHud(state) {
  runHudState=state;
  try { renderRunHud(); }
  catch(error) { setRunHudFailure(error,'presentación de totales'); }
}
let hovered = null, pinned = null;
let vehicleHighlights=[];
// Resolve the exact final marker already rendered this frame, including queue
// placement and turn pose. Never reconstruct a selected car from its route.
function displayedVehicle(object) {
  if(!object?.vehicle)return null;
  const row=visibilityRecords.get(object.vehicle),marker=row?.marker;
  return row?.visible && marker?.vehicle===object.vehicle && tripKey(marker)===tripKey(object) &&
    SimZ1VehiclePicking.key(marker)===SimZ1VehiclePicking.key(object) ? marker : null;
}
function refreshVehicleHighlights(submit=false) {
  if(!continuousMode)return;
  const selected=displayedVehicle(pinned),temporary=displayedVehicle(hovered);
  const candidates=[[selected,'pinned'],[temporary!==selected ? temporary : null,'hover']];
  const next=[];
  for(const [marker,mode] of candidates) {
    if(!marker)continue;
    const previous=vehicleHighlights.find(row=>row.marker===marker && row.mode===mode);
    if(previous){next.push(previous);continue;}
    const outline=SimZ1VehiclePicking.bodyOutline(marker);
    // Cyan stays distinct from every speed colour, including yellow/white.
    if(outline)next.push({marker,mode,outline,color:mode==='pinned' ? [105,224,255] : [255,218,70]});
  }
  if(next.length===vehicleHighlights.length && next.every((row,i)=>row===vehicleHighlights[i]))return;
  vehicleHighlights=next;
  layers=layers.map(layer=>layer.id==='vehicle-focus-halo' || layer.id==='vehicle-focus-outline' ?
    layer.clone({data:vehicleHighlights}) : layer);
  if(submit){deckInstance.setProps({layers});renderCounters.deckSubmissions++;}
}
let selectedHistory = [], selectedEndpoints = [], selectedItinerary = [], selectionChanged = true;
let journeyRequestSequence=0,journeyRequestAbort=null,fullJourneyKey=null,fullJourneyVehicle=null,fullJourneyRecords=null,selectionJourneyStatus=null;
let journeyLaneTimelines=new Map(),journeyRoutePlans=new WeakMap();
function tripKey(object) {
  if (!object?.vehicle) return null;
  const trip = object.Trip;
  return JSON.stringify([object.Agent_ID ?? trip?.Person_ID ?? null,
    trip?.Trip_ID != null ? ['id',trip.Trip_ID] : Number.isFinite(trip?.Departure) ? ['departure',trip.Departure] :
      ['segment',object.vehicle,...object.timestamps]]);
}
let recordsByTrip = new Map();
for (const record of replaySegments) {
  const key=tripKey(record);
  if (!recordsByTrip.has(key)) recordsByTrip.set(key,[]);
  recordsByTrip.get(key).push(record);
}
for (const records of recordsByTrip.values()) records.sort((a,b)=>a.timestamps[0]-b.timestamps[0]);
function recordsForTrip(object) {
  const key=tripKey(object);
  if (key==null) return [];
  if (key===fullJourneyKey && object.vehicle===fullJourneyVehicle && fullJourneyRecords) return fullJourneyRecords;
  return recordsByTrip.get(key) || (timelines.get(object.vehicle) || []).filter(r=>tripKey(r)===key);
}
function replayTrip(trip={}) {
  trip=trip || {};
  if (!continuousMode || Number.isFinite(trip.Arrival) && trip.Arrival<=FINAL ||
      Number.isFinite(trip.Abort) && (trip.Abort<FINAL || trip.Abort===FINAL && config.experimental_observation?.policy==='fixed-day-24h-v1') && trip.Status!=='censored') return trip;
  // A view over a legacy 25 h source must never convert its later arrival into
  // a completed trip in this day. Preserve source metadata and records intact.
  return {...trip,Arrival:null,Status:'censored',Censored_At_Day_End:true,
    Observation_End:FINAL,Observation_End_Provenance:'viewer_day_end'};
}
function selectionAt(object, time, records=null) {
  const key=tripKey(object);
  if (key==null) return {visible:false,reason:'no_trip',active:null};
  records=records ?? recordsForTrip(object);
  const trip=replayTrip(object.Trip);
  const departure=Number.isFinite(trip.Departure) ? trip.Departure : records[0]?.timestamps[0];
  let reason=null;
  if (!Number.isFinite(departure) || time<departure || continuousMode && departure>=FINAL) reason='before_departure';
  else if (continuousMode && time>=FINAL && trip.Censored_At_Day_End) reason='day_end_censored';
  else if (Number.isFinite(trip.Arrival)) {
    if (time>=trip.Arrival) reason='arrived'; // Arrival is exclusive, including zero-length trips.
  } else if (Number.isFinite(trip.Abort) && trip.Status!=='censored') {
    if (time>=trip.Abort) reason='aborted';
  } else {
    // A censored trip has no observed arrival. Never extend visibility to the
    // global replay clock merely because other agents still produce events.
    const last=Number.isFinite(trip.Last_Observed_Time) ? trip.Last_Observed_Time :
      records.reduce((end,record)=>Math.max(end,record.timestamps[1]),-Infinity);
    if (time>last) reason='after_last_observation';
    else if (Number.isFinite(trip.Observation_End) && trip.Observation_End_Provenance!=='last_event_in_stream' &&
             time>=trip.Observation_End) reason='observation_cutoff';
  }
  let active=null;
  if (!reason) for (const record of records) {
    if (record.timestamps[0]>time) break;
    if (time<record.timestamps[1]) active=record;
  }
  return {key,trip,records,visible:!reason || reason==='day_end_censored',reason:reason || (active ? 'measured_segment' : 'event_gap'),active};
}
function selectAgent(object) {
  const request=++journeyRequestSequence;
  journeyRequestAbort?.abort();journeyRequestAbort=null;selectionJourneyStatus=null;
  if(!object?.vehicle || tripKey(object)!==fullJourneyKey || object.vehicle!==fullJourneyVehicle) {
    fullJourneyKey=null;fullJourneyVehicle=null;fullJourneyRecords=null;
    journeyLaneTimelines=new Map();journeyRoutePlans=new WeakMap();
  }
  selectedHistory = []; selectedEndpoints = []; selectedItinerary = []; selectionChanged = true;
  if (!object?.vehicle) return;
  // The verified schedule is static evidence, independent from observed
  // traversals and from whether a current position can be reconstructed.
  if(continuousMode && object.Trip?.Transit) {
    const transit=SimZ1ContinuousLoader.transitTrip(object.Trip,object);
    selectedItinerary=transit.route_links.flatMap((id,occurrence)=>{
      const link=visualLaneRenderer?.links.get(id);
      if(!link?.geometry || spatialRenderer && !spatialRenderer.allowed.has(id))return [];
      return [{path:link.data.path,Link_ID:id,occurrence,vehicle:object.vehicle,
        journey_key:object.Replay_Journey_Key,trip_id:object.Trip.Trip_ID,
        position_evidence:'verified_transit_schedule',source:transit.source}];
    });
    if(spatialRenderer)selectedItinerary=spatialRenderer.paths(selectedItinerary);
  }
  selectedHistory = recordsForTrip(object);
  const trip = replayTrip(object.Trip);
  if(spatialRenderer)spatialRenderer.validateTrip(trip);
  const origin = trip?.Origin_Position || (!spatialRenderer ? selectedHistory[0]?.path[0] : null);
  if (origin && (!spatialRenderer || spatialRenderer.contains(origin))) selectedEndpoints.push({position:origin,kind:'origin'});
  if (trip?.Destination_Position && !trip.Censored_At_Day_End && (!spatialRenderer ||
      Number.isFinite(trip.Arrival) && trip.Status==='completed' && spatialRenderer.contains(trip.Destination_Position)))
    selectedEndpoints.push({position:trip.Destination_Position,kind:'destination',icon:'finish'});
  if ((config.pagination || continuousMode) && (tripKey(object)!==fullJourneyKey || object.vehicle!==fullJourneyVehicle)) {
    selectedHistory=[]; // No partial route is passed off as the complete journey.
    selectionJourneyStatus={key:tripKey(object),state:'loading'};
    journeyRequestAbort=typeof AbortController==='function' ? new AbortController() : null;
    loadCompleteJourney(object,request,journeyRequestAbort?.signal);
  }
}
async function loadCompleteJourney(object,request,signal) {
  const key=tripKey(object),serverKey=object.Replay_Journey_Key;
  const currentSelection=()=>!signal?.aborted && request===journeyRequestSequence &&
    tripKey(pinned)===key && pinned?.vehicle===object.vehicle;
  const sameIdentity=payload=>payload.run_id===config.hud.run_id && payload.iteration===config.hud.iteration &&
    (!continuousMode || payload.run_manifest_sha256===config.continuous.run_manifest_sha256 &&
      (config.continuous.source_version==null || payload.source_version===config.continuous.source_version) &&
      (payload.visual_policy ?? null)===(config.continuous.visual_policy ?? null));
  const began=performance.now();let outcome='failed';
  selectionRequests.started++;selectionRequests.pending++;
  try {
    if (!serverKey) throw new Error('Clave de viaje ausente');
    const query=new URLSearchParams({key:serverKey,run_id:config.hud.run_id,iteration:String(config.hud.iteration)});
    if (continuousMode) {
      query.set('run_manifest_sha256',config.continuous.run_manifest_sha256);
      if(config.continuous.source_version!=null)query.set('source_version',config.continuous.source_version);
      if(config.continuous.visual_policy!=null)query.set('visual_policy',config.continuous.visual_policy);
    }
    let response;
    for(let retry=0;;retry++) {
      if(!currentSelection()){outcome=signal?.aborted ? 'aborted' : 'stale';return;}
      selectionRequests.httpAttempts++;
      response=await fetch((config.continuous || config.pagination).journey_endpoint+'?'+query.toString(),{signal,cache:'no-store'});
      if(!currentSelection()){outcome=signal?.aborted ? 'aborted' : 'stale';return;}
      if(response.ok)break;
      let failure;try {failure=await response.json();} catch(_) {failure=null;}
      if(!currentSelection()){outcome=signal?.aborted ? 'aborted' : 'stale';return;}
      if(failure?.run_id!=null && !sameIdentity(failure))throw new Error('Respuesta de espera de otra identidad');
      if(response.status!==503 || failure?.retryable===false)
        throw new Error('Consulta local HTTP '+response.status+(failure?.error ? ': '+failure.error : ''));
      const backoff=Math.min(10000,1000*2**Math.min(retry,4));
      const header=response.headers?.get?.('Retry-After')?.trim();
      const requested=header ? (/^\d+(?:\.\d+)?$/.test(header) ? Number(header)*1000 : Date.parse(header)-Date.now()) : NaN;
      const delay=Number.isFinite(requested) ? Math.max(backoff,requested,0) : backoff;
      selectionRequests.retries503++;
      selectionJourneyStatus={key,state:'retrying',attempt:retry+1,retryAfterMs:delay,
        message:'Servidor ocupado; el recorrido se reintentará en '+Math.ceil(delay/1000)+' s.'};
      selectionChanged=true;render();
      await new Promise((resolve,reject)=>{
        let timer;
        const abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);
          const error=new Error('Consulta cancelada');error.name='AbortError';reject(error);};
        signal?.addEventListener('abort',abort,{once:true});
        timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},delay);
        if(signal?.aborted)abort();
      });
    }
    const payload=await response.json();
    if (!currentSelection()) {outcome=signal?.aborted ? 'aborted' : 'stale';return;}
    if (!sameIdentity(payload) || payload.key!==serverKey ||
        !Array.isArray(payload.records) || !payload.records.length ||
        payload.records.some(record=>record.Replay_Journey_Key!==serverKey || tripKey(record)!==key || record.vehicle!==object.vehicle)) {
      throw new Error('El recorrido recibido no corresponde a la corrida y viaje seleccionados');
    }
    if(continuousMode)for(const record of payload.records)SimZ1ContinuousLoader.transitTrip(record.Trip,record);
    if(spatialRenderer)for(const record of payload.records) {
      spatialRenderer.validateTrip(record.Trip);
      if(!spatialRenderer.allowed.has(record.Link_ID))throw new Error('Recorrido fuera de los enlaces espaciales validados');
    }
    // Journey evidence is independent of the currently loaded window. Older
    // endpoints without lanes remain on the source axis, never a hashed lane.
    const laneEvents=payload.lane_replay?.events ?? [];
    if(!Array.isArray(laneEvents) || laneEvents.some(event=>!event || event.vehicle!==object.vehicle ||
        !Number.isFinite(event.time) ||
        !['entered lane','left lane','vehicle enters traffic','vehicle leaves traffic'].includes(event.type) ||
        (['entered lane','left lane'].includes(event.type) &&
          (typeof event.link!=='string' || !event.link || typeof event.lane!=='string' || !event.lane))))
      throw new Error('Carriles del recorrido incompatibles');
    journeyLaneTimelines=new Map([[object.vehicle,laneEvents.slice().sort((a,b)=>a.time-b.time)]]);
    journeyRoutePlans=new WeakMap();
    fullJourneyKey=key;
    fullJourneyVehicle=object.vehicle;
    fullJourneyRecords=payload.records.sort((a,b)=>a.timestamps[0]-b.timestamps[0]);
    selectedHistory=fullJourneyRecords;selectionChanged=true;
    outcome='completed';selectionJourneyStatus={key,state:'complete'};render();
  } catch (error) {
    outcome=error.name==='AbortError' || signal?.aborted ? 'aborted' : 'failed';
    if (request!==journeyRequestSequence || tripKey(pinned)!==key || pinned?.vehicle!==object.vehicle) return;
    selectionJourneyStatus={key,state:'unavailable',message:'Recorrido completo no disponible: '+error.message};
    selectionChanged=true;render();
  } finally {
    selectionRequests.pending--;selectionRequests[outcome]++;
    selectionRequests.samples.push({outcome,elapsedMs:performance.now()-began});
    if(selectionRequests.samples.length>100)selectionRequests.samples.shift();
  }
}
const info = document.createElement('div');
info.id = 'simz1-active-telemetry';
info.style.display = 'none';
info.setAttribute('role','region');
info.tabIndex = 0;
info.setAttribute('aria-label','Informacion del agente, semaforo o incidente seleccionado');
(continuousMode ? technicalHelpContent : uiShell).append(info);
const journeyRetry = continuousMode ? document.createElement('button') : null;
const journeyStatus = continuousMode ? document.createElement('div') : null;
if(journeyStatus){journeyStatus.setAttribute('role','status');journeyStatus.hidden=true;hud.append(journeyStatus);}
const routeLegend=continuousMode ? document.createElement('div') : null;
if(continuousMode) {
  const source=layers.find(layer=>layer.id==='selected-future');
  if(source)layers.splice(layers.indexOf(source),0,
    source.clone({id:'selected-itinerary',data:[],getColor:[127,98,166,180],getWidth:1.5,widthMaxPixels:2}),
    source.clone({id:'selected-unresolved',data:[],getColor:[213,135,255,190],getWidth:3,widthMaxPixels:3}));
}
if(routeLegend) {
  routeLegend.id='simz1-route-legend';routeLegend.hidden=true;
  for(const [width,label] of [[4,'Observado'],[2,'Posterior registrado (no predicción)']]) {
    const swatch=document.createElement('span'),text=document.createElement('b');
    swatch.style.height=width+'px';swatch.style.background=width===4 ? '#d587ff' : '#f3e1ff';
    text.textContent=label;text.style.fontWeight='normal';routeLegend.append(swatch,text);
  }
  routeLegend.title='Carril registrado cuando existe evidencia; en otro caso, eje del enlace. Posición lateral aproximada.';
  const evidenceLabel=document.createElement('span');
  evidenceLabel.textContent=' · Itinerario verificado: tenue · Enlace registrado sin progreso reconstruible: violeta';
  routeLegend.append(evidenceLabel);
  hud.append(routeLegend);
}
if (journeyRetry) {
  journeyRetry.textContent='Reintentar recorrido';journeyRetry.hidden=true;
  journeyRetry.title='Volver a consultar el recorrido completo del agente seleccionado';
  journeyRetry.onclick=()=>{if(pinned?.vehicle){selectAgent(pinned);render();}};
  hud.append(journeyRetry);
}
function agentMetadataText(object) {
  const type = object.Agent_Type ?? 'No registrado (sin reclasificar el perfil historico)';
  return 'Tipo de agente: '+type+(object.Agent_Schema ? ' | Esquema: '+object.Agent_Schema : '')+
    '\nTipo vehicular: '+(object.Vehicle_Type ?? 'No registrado')+
    (object.Vehicle_Type_Source ? ' | Fuente: '+object.Vehicle_Type_Source : '')+
    '\nPCU registrado: '+(Number.isFinite(object.Vehicle_PCU) ? object.Vehicle_PCU : 'No disponible')+
    (object.Trip?.Transit ? '\nConductor interno: '+object.Trip.Driver_ID+
      '\nServicio: '+(object.Trip.Transit.service_id ?? object.Trip.Transit.line_id)+
      ' | Salida: '+object.Trip.Transit.departure_id+'\nActividad: '+SimZ1ContinuousLoader.transitState(object,current)?.state : '');
}
function tooltipText(object) {
  if (!object) return null;
  if(object.transit_stop && typeof SimZ1TransitStops!=='undefined')return SimZ1TransitStops.tooltip(object)?.text || null;
  if (object.incident) return 'Incidente registrado\nEnlace: ' + object.Link_ID +
    '\nEstado: ' + (incidentActive(object,current) ? 'Activo' : current < object.start ? 'Aun no iniciado' : 'Recuperado') +
    '\nInicio: ' + formatClock(object.start) + '\nRecuperacion: ' + (object.end == null ? 'No registrada' : formatClock(object.end)) +
    '\nCapacidad reducida: ' + object.capacity + ' veh/h\nVelocidad libre reducida: ' + (object.speed == null ? 'desconocida' : object.speed.toFixed(1)+' km/h');
  if (object.system_id != null || object.node) return 'Semaforo: ' + (object.system_id ?? object.node) + '\nEnlace entrante: ' +
    (object.Link_ID ?? 'Sin geometria disponible') +
    '\nGrupo nativo: ' + (object.group_id ?? 'Sin correspondencia') +
    '\nCarriles controlados: ' + (object.lane_ids?.join(', ') || 'Control por enlace / no disponible') +
    '\nEstado nativo: ' + signalStateAt(object.system_id,object.group_id,current) +
    '\nUltima emision: ' + (signalObservationAt(object.system_id,object.group_id,current)?.[0] ?? 'sin evento previo') +
    ' s; no se extrapolan ciclos'+(object.Signal_Geometry ?
      '\nCabeza 3D: '+(object.Signal_Geometry.reason || 'frente opuesto a la tangente final del acceso; +Z vertical')+
      '\nRumbo entrante: '+(object.Signal_Geometry.incoming_bearing_deg ?? 'desconocido')+
      '\nEtiqueta R/A/V: indicador legible del estado, no orientacion fisica.' : '');
  const state = selectionAt(object,current);
  if (!state.visible) return null;
  const active = state.active;
  const vehicle = active?.vehicle ?? object.vehicle;
  const visual = active ? visualQueueRecords.get(markerKey(active)) || markerAt(active, current) : null;
  const motion = active ? motionAt(active,current) : null;
  const trip = state.trip;
  const elapsed = trip?.Departure == null ? 'No disponible' : formatDuration(Math.max(0,Math.min(current,trip.Arrival ?? current)-trip.Departure));
  const lane = active ? laneObservationAt(vehicle, active.Link_ID, current) : {lane:null,event:null};
  const laneText = lane.lane ? '\nCola/carril registrado: ' + lane.lane +
    '\nEntrada registrada: ' + lane.event.time + ' s; ubicacion continua no observada' :
    '\nCola/carril actual: sin pertenencia observada en este instante';
  const lastLaneEvent = lane.event && !lane.lane && lane.event.lane ?
    '\nUltimo evento de cola: ' + (lane.event.type === 'left lane' ? 'salida' : 'entrada') +
    ' ' + lane.event.lane + ' a ' + lane.event.time + ' s' +
    (lane.event.entry_observed === false ? ' (sin entrada registrada)' : '') : '';
  return 'Agente: ' + object.Agent_ID + ' | Perfil: ' + ((active || object).Profile || 'No disponible') + '\nVehiculo: ' + vehicle + '\n' +
    agentMetadataText(active || object)+'\n'+
    'Viaje: ' + (trip?.Trip_ID ?? 'ID no disponible en este archivo') + '\n' +
    'Nodo de origen: ' + (trip?.Origin_Node ?? 'No disponible') + '\n' +
    'Nodo de destino: ' + (trip.Censored_At_Day_End ? 'Sin llegada observada en la jornada' : trip?.Destination_Node ?? 'No disponible (sin llegada)') + '\n' +
    (active ? 'Velocidad media medida del tramo: ' + (Number.isFinite(active.Speed_kmh) ? active.Speed_kmh.toFixed(1)+' km/h' : 'no disponible (limites inferidos o intervalo nulo)') + '\n'+(continuousMode ? 'Velocidad maxima del viaje fuente: ' : 'Velocidad maxima hasta aqui: ') + (Number.isFinite(active.Max_Speed_kmh) ? active.Max_Speed_kmh.toFixed(1)+' km/h' : 'no disponible') + '\nEnlace actual: ' + active.Link_ID : 'Sin tramo medido activo en este instante') +
    (visual ? '\nVelocidad visual estimada: ' + (Number.isFinite(visual.Visual_Speed_kmh) ? visual.Visual_Speed_kmh.toFixed(1) + ' km/h' : 'no disponible') +
      (visual.Waiting ? ' | Detenido en la interpolacion: '+(active.Wait_Evidence || 'causa no observada') : '') +
      '\nMovimiento visual: '+motionStatusLabel(visual.Visual_Motion_Status)+'; estimado entre eventos, no velocidad instantanea medida'+
      (visual.Visual_Motion_Fallback_Reason ? '\nMotivo del respaldo: '+visual.Visual_Motion_Fallback_Reason : '')+
      '\nWAIT nativo registrado: '+(Object.keys(active.Observed_Waits || {}).join(', ') || 'sin evidencia') : '') +
    (motion && !motion.available ? '\nMovimiento visual: no disponible; se conserva el intervalo nativo sin dibujar una trayectoria'+
      (motion.fallback_reason ? '\nMotivo: '+motion.fallback_reason : '') : '') +
    laneText + lastLaneEvent + (visual ? visualLaneText(visual)+visualQueueText(visual) : '\nPosicion actual: desconocida; no se unen huecos de eventos') +
    (trip.Censored_At_Day_End ? (config.temporal_policy ? '\nEstado al fin de observacion: censurado; sin llegada observada hasta el cierre' : '\nEstado en esta jornada: censurado a las 24 h; sin llegada observada hasta el cierre') :
      !Number.isFinite(trip.Arrival) ? '\nSin llegada registrada; seleccion limitada a la evidencia individual disponible' : '') +
    (selectionJourneyStatus?.key===tripKey(object) ?
      '\n'+(selectionJourneyStatus.state==='loading' ? 'Consultando recorrido completo del viaje...' :
        selectionJourneyStatus.state==='complete' ? (continuousMode ? 'Recorrido fuente cargado; vista limitada a 0..'+FINAL+' s.' : 'Recorrido completo del viaje cargado.') : selectionJourneyStatus.message) : '') +
    (spatialRenderer ? spatialRenderer.tripText(trip,current,formatDuration) : '\nTiempo transcurrido: ' + elapsed);
}
function formatDuration(seconds) {
  return [Math.floor(seconds/3600),Math.floor(seconds%3600/60),Math.floor(seconds%60)].map(v=>String(v).padStart(2,'0')).join(':');
}
// The continuous card is independent of the diagnostic text in Ayuda. Create
// its six nodes once; telemetry and pointer motion retain these DOM nodes.
const vehicleCard=continuousMode ? document.createElement('section') : null;
const vehicleCardClose=continuousMode ? document.createElement('button') : null;
const vehicleCardNodes=new Map();
const vehiclePositionStatus=partialVisualPolicy ? document.createElement('p') : null;
let vehicleCardPointer=null;
let vehicleCardState={visible:false,pinned:false,personId:null,vehicleId:null,fields:null};
if(vehicleCard) {
  vehicleCard.id='simz1-vehicle-card';vehicleCard.hidden=true;
  vehicleCard.setAttribute('aria-label','Información del vehículo');
  vehicleCardClose.id='simz1-vehicle-card-close';vehicleCardClose.type='button';
  vehicleCardClose.textContent='×';vehicleCardClose.setAttribute('aria-label','Cerrar información del vehículo');
  vehicleCardClose.onclick=event=>{event?.stopPropagation?.();clearSelection();};
  const rows=document.createElement('dl');
  for(const [key,label] of [['name','Nombre del agente'],['type','Tipo de agente'],
    ['currentSpeed','Velocidad actual (km/h)'],['maximumSpeed','Velocidad máxima (km/h)'],
    ['elapsed','Tiempo transcurrido en el viaje'],['estimatedDuration','Duración total estimada del viaje']]) {
    const term=document.createElement('dt'),value=document.createElement('dd');
    term.textContent=label;rows.append(term,value);vehicleCardNodes.set(key,value);
  }
  vehicleCard.append(vehicleCardClose,rows);uiShell.append(vehicleCard);
  if(vehiclePositionStatus) {
    vehiclePositionStatus.id='simz1-vehicle-position-status';vehiclePositionStatus.setAttribute('role','status');
    vehiclePositionStatus.hidden=true;vehicleCard.append(vehiclePositionStatus);
  }
}
function recordedAgentType(object) {
  // Continuous labels and geometry share one catalog; archived paged clients
  // without that module retain their raw metadata rather than inventing a type.
  return typeof SimZ1VehicleCatalog==='function' ? SimZ1VehicleCatalog.resolve(object).label :
    object.Agent_Type ?? object.Vehicle_Type ?? object.Profile ?? 'No registrado';
}
function formatSimulatedDuration(seconds) {
  if(!Number.isFinite(seconds) || seconds<0)return '—';
  const minutes=Math.floor(seconds/60),hours=Math.floor(minutes/60),rest=minutes%60;
  return (hours ? hours+' h'+(rest ? ' '+rest+' min' : '') : minutes+' min')+' simulados';
}
function cardSpeed(speed) {
  if(!Number.isFinite(speed) || speed<0)return '—';
  // Rounding a slow but moving vehicle to zero would fabricate a stop.
  return speed>0 && speed<0.05 ? '<0.1 km/h' : String(Math.round(speed*10)/10)+' km/h';
}
function buildVehicleCardFields(object,time,state=null) {
  state=state || selectionAt(object,time,[object]);
  // Person/trip route indexes can include a vehicle handoff. A vehicle card
  // must not borrow the other vehicle's speed or type at the same simulated time.
  const active=state.active?.vehicle===object.vehicle ? state.active : null;
  const metadata=active || object,trip=state.trip || {};
  // Without a vehicle, selectionAt has no trip state; retain the recorded
  // person as a historical name fallback, without assigning a vehicle ID.
  const person=object.Agent_ID ?? trip.Person_ID ?? object.Trip?.Person_ID;
  const motion=active ? motionAt(active,time) : null;
  let speed=motion?.available ? motion.speed_kmh : null;
  // Old interpolation can freeze a position without observed motion evidence.
  // A coincident pair of visual coordinates alone does not prove a stopped car.
  if(active && !active.Motion_Plan && speed===0 &&
      !['native_wait_observation','fixed_boundary_position'].includes(active.Wait_Evidence))speed=null;
  const maximum=metadata.Motion_Provenance?.vehicle_limit_mps ?? object.Motion_Provenance?.vehicle_limit_mps;
  let end=time;
  if(Number.isFinite(trip.Arrival) && time>=trip.Arrival)end=Math.min(end,trip.Arrival);
  if(Number.isFinite(trip.Abort) && trip.Status!=='censored' && time>=trip.Abort)end=Math.min(end,trip.Abort);
  if(trip.Status==='censored') {
    if(Number.isFinite(trip.Last_Observed_Time))end=Math.min(end,trip.Last_Observed_Time);
    if(Number.isFinite(trip.Observation_End))end=Math.min(end,trip.Observation_End);
    // replayTrip may add the daily cutoff; an earlier native cutoff still wins.
    if(Number.isFinite(object.Trip?.Observation_End))end=Math.min(end,object.Trip.Observation_End);
    if(state.reason==='after_last_observation')
      end=Math.min(end,state.records.reduce((last,record)=>Math.max(last,record.timestamps[1]),-Infinity));
  }
  // Departure is a native event. The first segment in a loaded window is not
  // necessarily the start of the trip, so absence stays unknown.
  const elapsed=Number.isFinite(trip.Departure) && time>=trip.Departure ? end-trip.Departure : null;
  return {name:object.vehicle!=null ? 'Vehículo '+String(object.vehicle) : person!=null ? 'Vehículo '+String(person) : 'Vehículo —',
    type:recordedAgentType(metadata),currentSpeed:cardSpeed(speed),
    maximumSpeed:cardSpeed(Number.isFinite(maximum) && maximum>0 ? maximum*3.6 : null),
    elapsed:formatSimulatedDuration(elapsed),
    // Current exports contain observations, not an ex-ante duration forecast.
    // Arrival, future recorded links and Max_Speed_kmh must not become one.
    estimatedDuration:'—'};
}
function positionVehicleCard() {
  if(!vehicleCard || vehicleCard.hidden)return;
  const margin=8,width=window.innerWidth || 1024,height=window.innerHeight || 768;
  const rect=deckInstance.getCanvas?.()?.getBoundingClientRect?.() || {left:0,top:0,right:width,bottom:height};
  const cardWidth=vehicleCard.offsetWidth || Math.min(280,width-2*margin);
  const cardHeight=vehicleCard.offsetHeight || 240;
  const left=vehicleCardState.pinned ? Math.min(rect.right,width)-cardWidth-margin :
    (vehicleCardPointer?.x ?? rect.left)+14;
  const top=vehicleCardState.pinned ? Math.max(rect.top,0)+margin : (vehicleCardPointer?.y ?? rect.top)+14;
  vehicleCard.style.left=Math.max(margin,Math.min(width-cardWidth-margin,left))+'px';
  vehicleCard.style.top=Math.max(margin,Math.min(height-cardHeight-margin,top))+'px';
}
function updateVehicleCard() {
  if(!vehicleCard)return;
  const object=pinned?.vehicle ? pinned : !pinned && hovered?.vehicle ? visibleInspection(hovered,true) : null;
  const wasVisible=vehicleCardState.visible,wasPinned=vehicleCardState.pinned;
  if(!object) {
    vehicleCard.hidden=true;vehicleCardState={visible:false,pinned:false,personId:null,vehicleId:null,fields:null};return;
  }
  const state=selectionAt(object,current),fields=buildVehicleCardFields(object,current,state);
  vehicleCardState={visible:true,pinned:Boolean(pinned?.vehicle),personId:object.Agent_ID ?? object.Trip?.Person_ID ?? null,
    vehicleId:object.vehicle,fields};
  for(const [key,node] of vehicleCardNodes)if(node.textContent!==fields[key])node.textContent=fields[key];
  vehicleCard.setAttribute('data-pinned',String(vehicleCardState.pinned));
  vehicleCardClose.hidden=!vehicleCardState.pinned;vehicleCard.hidden=false;
  if(vehiclePositionStatus) {
    const pending=visibilityRecords.get(object.vehicle)?.reason==='reconstruction_pending';
    vehiclePositionStatus.hidden=!pending;
    vehiclePositionStatus.textContent=pending ? 'Posición no disponible / reconstrucción pendiente' : '';
  }
  if(!wasVisible || wasPinned!==vehicleCardState.pinned)positionVehicleCard();
}
function hoverVehicleCard(info,event) {
  if(cameraDragging)return;
  hovered=inspectPointer(info,event);
  const rect=deckInstance.getCanvas?.()?.getBoundingClientRect?.() || {left:0,top:0};
  const source=event?.srcEvent || event;
  vehicleCardPointer={x:Number.isFinite(source?.clientX) ? source.clientX : rect.left+(info?.x || 0),
    y:Number.isFinite(source?.clientY) ? source.clientY : rect.top+(info?.y || 0),
    pointerType:event?.pointerType || source?.pointerType || lastPointerType};
  updateVehicleCard();if(!pinned)positionVehicleCard();
  refreshVehicleHighlights(true);
  if(!hovered?.vehicle || technicalHelp.open)updateTechnicalInspection();
}
function updateTechnicalInspection() {
  info.textContent=tooltipText(visibleInspection(pinned) || hovered) || '';
  info.style.display=info.textContent ? 'block' : 'none';
}
let vehicleHoverCheck=null;
function checkVehicleHover() {
  if(!hovered?.vehicle || !vehicleCardPointer){vehicleHoverCheck=null;return;}
  const previousState=selectionAt(hovered,current);
  const previousValid=previousState.active?.vehicle===hovered.vehicle && visibilityRecords.get(hovered.vehicle)?.visible!==false;
  // Re-evaluate the current bodies after movement/seek. A previous vehicle's
  // aperture must not retain the card over a different body's interior.
  const viewport=currentDeckViewport();
  if(!viewport?.project){if(!previousValid){hovered=null;vehicleHoverCheck=null;}return;}
  const markers=layers.find(layer=>layer.id==='trips')?.props.data || [];
  const rect=deckInstance.getCanvas?.()?.getBoundingClientRect?.() || {left:0,top:0};
  const x=vehicleCardPointer.x-rect.left,y=vehicleCardPointer.y-rect.top;
  const pointerType=vehicleCardPointer.pointerType || lastPointerType;
  if(previousValid && vehicleHoverCheck?.markers===markers && vehicleHoverCheck.viewport===viewport &&
     vehicleHoverCheck.x===x && vehicleHoverCheck.y===y && vehicleHoverCheck.pointerType===pointerType)return;
  vehicleHoverCheck={markers,viewport,x,y,pointerType};
  // No work is repeated for an unchanged paused frame; no journey query or
  // marker reconstruction is needed to select from this rendered roster.
  hovered=SimZ1VehiclePicking.pick(markers,{x,y,
    width:viewport.width,height:viewport.height,pointerType,
    project:position=>viewport.project(position)})?.object || null;
  if(hovered && (selectionAt(hovered,current).active?.vehicle!==hovered.vehicle ||
                visibilityRecords.get(hovered.vehicle)?.visible===false)) {
    hovered=null;vehicleHoverCheck=null;
  }
}
function formatClock(seconds,format=clockFormat) {
  // Simulation time only: no calendar date or host timezone.
  if(config.temporal_policy) {
    const delta=Math.floor(seconds-config.temporal_policy.windows.study.start_seconds);
    const day=Math.floor(delta/86400),clock=delta-day*86400,hour=Math.floor(clock/3600);
    const value=format==='24h' ? formatDuration(clock) :
      [hour%12||12,Math.floor(clock%3600/60),clock%60].map(v=>String(v).padStart(2,'0')).join(':')+(hour<12?' AM':' PM');
    return 'D'+(day>=0?'+':'')+day+' '+value+' GT'+(seconds===FINAL?' (fin de observación)':'');
  }
  if (continuousMode) {
    if (!Number.isFinite(seconds) || seconds<INITIAL || seconds>FINAL) return 'Fuera de jornada';
    if (seconds===FINAL) return '24:00:00 (fin de observación)';
    if (format==='24h') return formatDuration(Math.floor(seconds));
  }
  if (seconds >= 86400) return formatDuration(Math.floor(seconds)) + ' (dia ' + (Math.floor(seconds/86400)+1) + ')';
  const time = ((Math.floor(seconds) % 86400) + 86400) % 86400;
  const hour = Math.floor(time / 3600);
  return [hour % 12 || 12, Math.floor(time % 3600 / 60), time % 60]
    .map(v => String(v).padStart(2, '0')).join(':') + (hour < 12 ? ' AM' : ' PM');
}
function setClockFormat(format) {
  if (format!=='12h' && format!=='24h') throw new Error('Formato admitido: 12h o 24h');
  clockFormat=format;
  if(clockFormatButton) {
    clockFormatButton.textContent=format==='24h' ? '12 h' : '24 h';
    clockFormatButton.title='Cambiar reloj a formato de '+(format==='24h' ? '12' : '24')+' horas';
  }
  render();
}
// White means an actually stationary visual state, allowing only numerical
// roundoff up to 0.0001 km/h. A slow moving vehicle (e.g. 10 km/h) stays red.
const MOTION_STOP_TOLERANCE_KMH = 1e-4;
function motionStatusLabel(status) {
  if(status==='observed_event_position')return 'posicion de entrada nativa en este instante; velocidad no observada';
  return ({kinematic:'aceleracion y frenado progresivos',constant:'velocidad constante',
    stationary:'posicion fija',fallback:'interpolacion de respaldo',legacy:'interpolacion heredada',
    unavailable:'movimiento no disponible'})[status] || 'interpolacion estimada';
}
function visualSpeedColor(speed) {
  if (!Number.isFinite(speed)) return speedColors.unknown;
  if (speed <= MOTION_STOP_TOLERANCE_KMH) return speedColors.stopped;
  return speed > 40 ? speedColors.fast : speed >= 15 ? speedColors.medium : speedColors.slow;
}
const speedColors={unknown:[160,160,180],stopped:[255,255,255],fast:[40,210,95],medium:[255,210,40],slow:[245,65,65]};
const markerMemo=new WeakMap(),entityMemo=new WeakMap(),presentationMemo=new WeakMap();
// Validation is invariant under time and speed for immutable database plans.
const validatedMotionPlans = new WeakMap();
function motionAt(segment, time) {
  if(!Array.isArray(segment?.timestamps) || segment.timestamps.length!==2 || !segment.timestamps.every(Number.isFinite) ||
     segment.timestamps[1]<=segment.timestamps[0] || !Array.isArray(segment.path) || segment.path.length<2 ||
     !segment.path.every(p=>Array.isArray(p) && p.length>=2 && p.slice(0,2).every(Number.isFinite)))
    return {available:false,status:'unavailable',fallback_reason:'intervalo abierto, nulo o geometria incompleta'};
  const [start, end] = segment.timestamps;
  const plan = segment.Motion_Plan;
  const phases = plan?.phases;
  const epsilon = 1e-7;
  const unavailable = reason => ({available:false,status:'unavailable',source:plan?.source || 'estimated_motion_phases',
    fallback_reason:reason || 'intervalo incompatible con una trayectoria visual acotada'});
  if (plan?.status === 'unavailable') {
    const boundary=segment.Boundary_Provenance;
    // A bounded continuous path may be impossible between discrete QSim ticks,
    // while the link-entry endpoint itself is explicitly observed. Display
    // only that exact instant; neither infer a speed nor fill the open interval.
    if(time===start && boundary?.start==='entered link' && boundary.start_relative===0)
      return {available:true,fraction:0,distance_m:0,speed_kmh:null,acceleration_mps2:null,
        waiting:false,status:'observed_event_position',source:'native_entered_link_at_exact_timestamp',
        fallback_reason:plan.fallback_reason,instant_only:true};
    return unavailable(plan.fallback_reason);
  }
  const distanceEpsilon = epsilon*Math.max(1,plan?.distance_m || 0);
  const phaseDistanceEnd = phase => phase[2]+phase[3]*(phase[1]-phase[0])+0.5*phase[4]*(phase[1]-phase[0])**2;
  // Evaluation depends only on absolute simulation time. No frame integration,
  // wall-clock speed, previous position or day wrapping enters the trajectory.
  const cachedValidation = plan && validatedMotionPlans.get(plan);
  const valid = cachedValidation && cachedValidation.start===start && cachedValidation.end===end ? cachedValidation.valid :
    plan?.version === 1 && Number.isFinite(plan.distance_m) && plan.distance_m >= 0 &&
    Array.isArray(phases) && phases.length > 0 && phases.every((phase,index) =>
      Array.isArray(phase) && phase.length >= 5 && phase.slice(0,5).every(Number.isFinite) &&
      phase[1] >= phase[0] && phase[3]>=-epsilon && phase[3]+phase[4]*(phase[1]-phase[0])>=-epsilon &&
      phase[2]>=-distanceEpsilon && phaseDistanceEnd(phase)<=plan.distance_m+distanceEpsilon &&
      (!Number.isFinite(plan.cap_mps) || Math.max(phase[3],phase[3]+phase[4]*(phase[1]-phase[0]))<=plan.cap_mps+epsilon) &&
      (!index || Math.abs(phase[0]-phases[index-1][1]) <= epsilon && Math.abs(phase[2]-phaseDistanceEnd(phases[index-1]))<=distanceEpsilon)) &&
    Math.abs(phases[0][0]-start) <= epsilon && Math.abs(phases[phases.length-1][1]-end) <= epsilon &&
    Math.abs(phases[0][2])<=distanceEpsilon && Math.abs(phaseDistanceEnd(phases[phases.length-1])-plan.distance_m)<=distanceEpsilon;
  if (plan && !cachedValidation) validatedMotionPlans.set(plan,{start,end,valid});
  if (valid) {
    const absoluteTime = Math.max(start,Math.min(end,time));
    let lo=0, hi=phases.length;
    while (lo<hi) { const mid=(lo+hi)>>>1; if(phases[mid][0]<=absoluteTime) lo=mid+1; else hi=mid; }
    const phase = phases[Math.max(0,lo-1)];
    const [t0,t1,s0,v0,a] = phase;
    const dt = Math.max(0,Math.min(t1-t0,absoluteTime-t0));
    const distance = Math.max(0,Math.min(plan.distance_m,s0+v0*dt+0.5*a*dt*dt));
    const speed = Math.max(0,v0+a*dt)*3.6;
    return {available:true,fraction:plan.distance_m > 0 ? distance/plan.distance_m : 0,
      distance_m:distance,speed_kmh:speed,acceleration_mps2:a,
      waiting:time>=start && time<end && speed<=MOTION_STOP_TOLERANCE_KMH,
      status:plan.status || 'kinematic',source:plan.source || 'estimated_motion_phases',
      fallback_reason:plan.fallback_reason || null};
  }
  if (plan) return unavailable('plan de movimiento incompleto o incompatible');
  // Preserve old exports explicitly as a fallback; their native timestamps and
  // measured Speed_kmh remain unchanged. Unknown speed is never painted white.
  const moveEnd = Math.max(start,Math.min(end,segment.Movement_End ?? end));
  const fraction = moveEnd > start ? Math.max(0,Math.min(1,(time-start)/(moveEnd-start))) : 1;
  const stationary = segment.path[0].every((value,i) => value === segment.path[1][i]);
  const fixed = stationary || time >= moveEnd;
  const estimate = segment.Motion_Speed_kmh ?? segment.Speed_kmh;
  const speed = fixed ? 0 : Number.isFinite(estimate) ? Math.max(0,estimate) : null;
  return {available:true,fraction,distance_m:null,speed_kmh:speed,acceleration_mps2:null,
    waiting:time>=start && time<end && Number.isFinite(speed) && speed<=MOTION_STOP_TOLERANCE_KMH,
    status:plan ? 'fallback' : 'legacy',source:segment.Motion_Provenance?.method || 'legacy_interval_interpolation',
    fallback_reason:plan ? 'plan de movimiento incompleto o incompatible' :
      segment.Motion_Provenance?.fallback_reason || 'archivo anterior sin fases de aceleracion'};
}
function centerPosition(segment, fraction) {
  return segment.path[0].map((value,i) => value + fraction*(segment.path[1][i]-value));
}
function visualLaneText(marker) {
  if (!marker.Visual_Lane_Source || marker.Visual_Lane_Source === 'centerline') return '\nPosicion: interpolada sobre el eje; carril visual no disponible'+
    (marker.Visual_Lane_Reason ? ' ('+marker.Visual_Lane_Reason+')' : '');
  return '\nCarril visual: '+(marker.Visual_Lane_Index+1)+' ('+
    (marker.Visual_Lane_Source==='native' ? 'ID nativo' : marker.Native_Occupancy ? 'reserva del modelo' : 'asignacion estimada')+')'+
    '\nDesplazamiento lateral estimado: '+marker.Visual_Lane_Offset_Meters.toFixed(2)+' m; no es una maniobra fisica'+
    (Number.isFinite(marker.Native_Occupancy?.footprint_m) ? '\nEspacio reservado: '+marker.Native_Occupancy.footprint_m.toFixed(2)+' m; cuerpo y separacion. Posicion dibujada estimada.' : '');
}
function reconstructionPending(segment) {
  return Boolean(partialVisualPolicy && segment && queueContexts.get(
    JSON.stringify([segment.vehicle,segment.Replay_Journey_Key ?? '',segment.Link_ID,segment.timestamps]))?.reason==='reconstruction_pending');
}
function markerAt(segment, time, observation=null, context=null) {
  const motion = motionAt(segment,time);
  if (!motion.available) return null;
  const lane = observation ?? laneObservationAt(segment.vehicle, segment.Link_ID, time,true,context?.laneTimelines ?? laneTimelines);
  const next=(context?.transitionRecords ?? transitionRecords).get(markerKey(segment))?.next;
  const queueContext=continuousMode ? (context?.queueContexts ?? queueContexts).get(
    JSON.stringify([segment.vehicle,segment.Replay_Journey_Key ?? '',segment.Link_ID,segment.timestamps])) : undefined;
  const saved=markerMemo.get(segment);
  if(saved && saved.event===lane.event && saved.lane===lane.lane && saved.next===next && saved.queueContext===queueContext &&
    saved.motion.fraction===motion.fraction && saved.motion.speed_kmh===motion.speed_kmh &&
    saved.motion.waiting===motion.waiting && saved.motion.acceleration_mps2===motion.acceleration_mps2) {
    renderCounters.markerReuses++;return saved.marker;
  }
  const center = centerPosition(segment,motion.fraction);
  const placement = visualLaneRenderer ? visualLaneRenderer.marker(segment,motion.fraction,
    {...lane,next_segment:next},center) : {position:center};
  let entity=entityMemo.get(segment);
  if(!entity){entity=JSON.stringify([config.continuous?.run_id ?? config.hud?.run_id,segment.vehicle,segment.Replay_Journey_Key ?? tripKey(segment)]);entityMemo.set(segment,entity);}
  let presentation=presentationMemo.get(segment);
  if(!presentation && typeof SimZ1VehicleCatalog==='function') {
    presentation=SimZ1VehicleCatalog.resolve(segment);presentationMemo.set(segment,presentation);
  }
  const marker={...segment, Waiting:motion.waiting, Visual_Speed_kmh:motion.speed_kmh,Visual_Motion_Fraction:motion.fraction,
    Visual_Native_Center_Position:center,
    Visual_Queue_Context:queueContext ?? (continuousMode ? {complete:false,reason:'queue_context_unavailable'} : undefined),
    Visual_Entity_ID:entity,Visual_Vehicle_Presentation:presentation,
    Visual_Acceleration_mps2:motion.acceleration_mps2, Visual_Distance_m:motion.distance_m,
    Visual_Motion_Status:motion.status, Visual_Motion_Source:motion.source,
    Visual_Motion_Fallback_Reason:motion.fallback_reason, color:presentation?.family==='truck' ? [172,95,230,255] : visualSpeedColor(motion.speed_kmh),
    Observed_Queue_ID:lane.lane,Observed_Queue_Entry:lane.lane ? lane.event.time : null, Position_Evidence:placement.Visual_Lane_Source==='native' ?
      'native_lane_id_with_estimated_lateral_position' : placement.Visual_Lane_Source==='estimated' ?
      'estimated_visual_lane_position' : 'interpolated_link_centerline', ...placement};
  markerMemo.set(segment,{event:lane.event,lane:lane.lane,next,queueContext,motion,marker});renderCounters.markerCreates++;return marker;
}
function routeSlice(geometry,offset,from,to) {
  if(!Number.isFinite(from) || !Number.isFinite(to) || to-from<=1e-10)return [];
  const fractions=[from,...geometry.distances.slice(1,-1).map(d=>d/geometry.length).filter(f=>f>from && f<to),to];
  const points=fractions.map(f=>visualLaneRenderer.sample(geometry,f,offset)?.position);
  return points.every(Boolean) ? points : [];
}
function routePlan(segment) {
  if(journeyRoutePlans.has(segment))return journeyRoutePlans.get(segment);
  const parts=[],[start,end]=segment.timestamps;
  const link=visualLaneRenderer?.links.get(segment.Link_ID);
  const compatible=link?.geometry && visualLaneRenderer.compatiblePath(link,segment.path);
  // Prefer a recorded polyline, or the compatible network geometry when the
  // replay stores only endpoints. Never insert a connector between records.
  const geometry=compatible && segment.path.length===2 ? link.geometry : visualLaneRenderer?.geometry(segment.path);
  if(geometry && Number.isFinite(start) && Number.isFinite(end) && start<end) {
    if(start<FINAL && end>INITIAL && !motionAt(segment,(Math.max(start,INITIAL)+Math.min(end,FINAL))/2).available) {
      // A known link remains observed geometry; without motion evidence it
      // cannot be divided into past/future or used as a vehicle position.
      parts.push({start:Math.max(start,INITIAL),end:Math.min(end,FINAL),unresolved:true,row:{
        path:compatible && segment.path.length===2 ? link.data.path : segment.path,
        Link_ID:segment.Link_ID,vehicle:segment.vehicle,timestamps:[start,end],lane:null,
        position_evidence:'observed_link_geometry_unknown_progress'}});
      journeyRoutePlans.set(segment,parts);return parts;
    }
    const events=journeyLaneTimelines.get(segment.vehicle) || [];
    let lo=0,hi=events.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(events[mid].time<=start)lo=mid+1;else hi=mid;}
    const boundaries=[Math.max(INITIAL,start)];
    for(let i=lo;i<events.length && events[i].time<Math.min(FINAL,end);i++)
      if(events[i].time>boundaries.at(-1))boundaries.push(events[i].time);
    boundaries.push(Math.min(FINAL,end));
    for(let i=1;i<boundaries.length;i++) {
      const a=boundaries[i-1],b=boundaries[i];if(a>=b)continue;
      const first=motionAt(segment,a),last=motionAt(segment,b);
      if(!first.available || !last.available || last.fraction<first.fraction)continue;
      const observation=laneObservationAt(segment.vehicle,segment.Link_ID,a,true,journeyLaneTimelines);
      const placement=compatible && observation.event?.time>=start ?
        visualLaneRenderer.marker(segment,first.fraction,observation,segment.path[0]) : null;
      const native=placement?.Visual_Lane_Source==='native' ? link.data.native_lanes[observation.lane] : null;
      const length=link?.data.length_m || geometry.length;
      const nativeStart=native ? Math.max(0,1-native.start_m/length) : 1;
      const offset=native ? placement.Visual_Lane_Offset_Meters : 0;
      // A short terminal lane does not authorize an offset on the whole link.
      const cuts=native && first.fraction<nativeStart && last.fraction>nativeStart ?
        [first.fraction,nativeStart,last.fraction] : [first.fraction,last.fraction];
      for(let j=1;j<cuts.length;j++) {
        const from=cuts[j-1],to=cuts[j];let useNative=native && from>=nativeStart;
        let lateral=useNative ? offset : 0,path=routeSlice(geometry,lateral,from,to);
        if(path.length<2 && useNative) {useNative=false;lateral=0;path=routeSlice(geometry,0,from,to);}
        if(path.length<2)continue;
        parts.push({start:a,end:b,from,to,geometry,offset:lateral,row:{path,Link_ID:segment.Link_ID,
          vehicle:segment.vehicle,timestamps:[start,end],lane:useNative ? observation.lane : null,
          position_evidence:useNative ? 'native_lane_estimated_lateral_position' : 'source_link_axis'}});
      }
    }
  }
  journeyRoutePlans.set(segment,parts);return parts;
}
function splitSelectedRoute(records, time) {
  const history = [], future = [], unresolved = [];
  if (!records.length || !selectionAt(records[0],time,records).visible) return {history,future,unresolved};
  if(continuousMode) {
    for(const segment of records)for(const part of routePlan(segment)) {
      if(part.unresolved){unresolved.push(part.row);continue;}
      if(time>=part.end)history.push(part.row);
      else if(time<=part.start)future.push(part.row);
      else {
        const motion=motionAt(segment,time);if(!motion.available)continue;
        const at=Math.max(part.from,Math.min(part.to,motion.fraction));
        for(const [target,from,to] of [[history,part.from,at],[future,at,part.to]]) {
          const path=routeSlice(part.geometry,part.offset,from,to);
          if(path.length>1)target.push({...part.row,path});
        }
      }
    }
    return spatialRenderer ? {history:spatialRenderer.paths(history),future:spatialRenderer.paths(future),unresolved:spatialRenderer.paths(unresolved)} : {history,future,unresolved};
  }
  // Keep measured segments separate: never bridge missing events across links.
  for (const segment of records) {
    const [start, end] = segment.timestamps;
    const visibleStart=continuousMode ? Math.max(INITIAL,start) : start;
    const visibleEnd=continuousMode ? Math.min(FINAL,end) : end;
    if(visibleStart>=visibleEnd)continue;
    if (!motionAt(segment,Math.max(start,Math.min(end,time))).available) continue;
    // Route evidence remains on the source axis: window-local lane events must
    // not invent a lateral history for the complete selected journey.
    const from=visibleStart===start ? segment.path[0] : centerPosition(segment,motionAt(segment,visibleStart).fraction);
    const to=visibleEnd===end ? segment.path[1] : centerPosition(segment,motionAt(segment,visibleEnd).fraction);
    const path=visibleStart===start && visibleEnd===end ? segment.path : [from,to];
    if (time >= visibleEnd) history.push({path});
    else if (time <= visibleStart) future.push({path});
    else {
      const position = centerPosition(segment,motionAt(segment,time).fraction);
      history.push({path:[from, position]});
      future.push({path:[position, to]});
    }
  }
  return spatialRenderer ? {history:spatialRenderer.paths(history),future:spatialRenderer.paths(future)} : {history, future};
}
let lastMarkerTime = null;
let activeAgentCount = 0;
let visibleMarkerCount = 0;
let visualLaneCounts = {estimatedMarkers:0,nativeMarkers:0,centerlineMarkers:0};
let visualQueueCounts={waitingEvidence:0,positioned:0,overflow:0,unrepresentable:0,redistributed:0,unknownPositionWait:0,bodyUnrepresentable:0};
let visualQueueRecords=new Map();
let transitionRecords=new Map(),transitionTimelines=new Map(),transitionPoseCache=new Map(),visibilityRecords=new Map();
let queueRosterCache=null,visualFrameDiagnostics=null;
let queueContexts=new Map();
function indexTransitions(records) {
  transitionRecords=new Map();transitionTimelines=new Map();transitionPoseCache=new Map();
  queueRosterCache=null;
  const groups=new Map();
  for(const record of records) {
    if(!transitionTimelines.has(record.vehicle))transitionTimelines.set(record.vehicle,[]);
    transitionTimelines.get(record.vehicle).push(record);
    const key=JSON.stringify([record.vehicle,record.Replay_Journey_Key ?? tripKey(record)]);
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(record);
  }
  for(const group of transitionTimelines.values())group.sort((a,b)=>a.timestamps[0]-b.timestamps[0]);
  for(const group of groups.values()) {
    group.sort((a,b)=>a.timestamps[0]-b.timestamps[0] || a.timestamps[1]-b.timestamps[1]);
    for(let i=0;i<group.length;i++)transitionRecords.set(markerKey(group[i]),{previous:group[i-1],next:group[i+1]});
  }
}
function transitionNeighbors(marker) {
  const key=markerKey(marker);
  if(transitionPoseCache.has(key))return transitionPoseCache.get(key);
  const pair=transitionRecords.get(key) || {},previous=pair.previous;
  const poses={previous:previous ? markerAt(previous,previous.timestamps[1],
    laneObservationAt(previous.vehicle,previous.Link_ID,previous.timestamps[1],false)) : null,
    next:pair.next ? markerAt(pair.next,pair.next.timestamps[0]) : null};
  transitionPoseCache.set(key,poses);return poses;
}
function queueHoldTime(record) {
  return SimZ1ContinuousLoader.facilityDepartureHold(record) ?? record.Motion_Plan?.hold_start ?? record.Motion_Plan?.native_wait_boundary ??
    (record.Motion_Plan?.status==='stationary' && record.Boundary_Provenance?.start==='VehicleArrivesAtFacility' &&
     record.Boundary_Provenance?.end==='VehicleDepartsAtFacility' ? record.timestamps[0] : null) ??
    (record.Native_Occupancy?.policy==='corridor-length-v1' ? record.timestamps[0] : null);
}
function queueRoster() {
  if(queueRosterCache)return queueRosterCache;
  queueRosterCache=[];
  for(const records of transitionTimelines.values())for(const record of records) {
    const hold=queueHoldTime(record);
    if(!Number.isFinite(hold))continue;
    const pose=markerAt(record,hold);
    if(pose)queueRosterCache.push(pose);
  }
  return queueRosterCache;
}
function diagnosticProvenance() {
  return {run_id:config.continuous?.run_id ?? config.hud?.run_id ?? null,
    iteration:config.continuous?.iteration ?? config.hud?.iteration ?? null,
    run_manifest_sha256:config.continuous?.run_manifest_sha256 ?? null,
    replay_source:config.replay_source ?? null,client_build:window.simz1ClientBuild ?? null,
    deck_gl_version:window.deck?.VERSION ?? null,...(partialVisualPolicy ? {
      visual_policy:partialVisualPolicy.policy,native_status:partialVisualPolicy.native_status,
      native_validation:partialVisualPolicy.native_validation,visual_certification:'partial_not_certified'} : {})};
}
function getVisualDiagnostics(time=current) {
  const loaded=Number.isFinite(time) && time>=INITIAL && time<=FINAL && continuousReplay &&
    continuousReplay.activeIndex===continuousReplay.indexAt(time);
  if(!loaded)return {...diagnosticProvenance(),time,status:'window_not_loaded',records:[],collisions:[],
    synthetic_incidents:incidentEffects?.snapshot(time) ?? {status:'module_unavailable',adapter_installed:false}};
  if(visualFrameDiagnostics?.time===time)return visualFrameDiagnostics;
  // Read-only evaluation includes the entire active roster, never just the
  // requested vehicle. No seek, playback state or saved frame is changed.
  const byVehicle=new Map(),invalid=[],poses=[];
  for(const record of activeRecordsAt(time)) {
    if(record.Trip?.Departure>=FINAL)continue;
    byVehicle.set(record.vehicle,byVehicle.has(record.vehicle) ? null : record);
  }
  for(const [vehicle,record] of byVehicle) {
    const pose=record && markerAt(record,time);
    if(pose)poses.push(pose);
    else invalid.push({vehicle_id:vehicle,time,visible:false,position:null,reason:reconstructionPending(record) ? 'reconstruction_pending' : record ? 'motion_unavailable' : 'overlapping_intervals',
      link_id:record?.Link_ID ?? null,motion_reason:record ? motionAt(record,time).fallback_reason : null});
  }
  const frame=visualQueueRenderer?.frame(poses,time,transitionNeighbors,queueRoster());
  const records=[...(frame?.diagnostics.records || poses.map(m=>{
    const pending=partialVisualPolicy && m.Visual_Queue_Context?.reason==='reconstruction_pending';
    return {vehicle_id:m.vehicle,time,link_id:m.Link_ID,lane:m.Visual_Lane_Index ?? null,
      position:pending ? null : m.position,visible:!pending,reason:pending ? 'reconstruction_pending' : 'visible'};
  })),...invalid];
  if(spatialRenderer)for(const record of records)if(record.visible && !spatialRenderer.markerVisible({
      Link_ID:record.link_id,position:record.position,Visual_Native_Center_Position:record.native_position})) {
    record.visible=false;record.reason='spatial_filter';
  }
  return completeVisualDiagnostics(time,frame?.diagnostics,records);
}
function completeVisualDiagnostics(time,diagnostics,records) {
  const reasons={};for(const r of records)if(!r.visible)reasons[r.reason]=(reasons[r.reason] || 0)+1;
  const visible=records.filter(r=>r.visible).length;
  const missingContext=records.filter(row=>row.reason==='queue_context_incomplete');
  return {...diagnosticProvenance(),time,status:'evaluated',records,
    synthetic_incidents:incidentEffects?.snapshot(time) ?? {status:'module_unavailable',adapter_installed:false},
    get collisions(){return diagnostics?.collisions || [];},limitations:[...(diagnostics?.limitations || []).filter(row=>
    row.reason!=='hold_roster_may_precede_loaded_window')],
    sampleCollisions:diagnostics?.sampleCollisions,summarizeCollisions:diagnostics?.summarizeCollisions,
    collision_sample:diagnostics?.collision_sample ?? {total_pairs:0,returned:0,truncated:false,limit:100},
    context_scope:'bounded_native_hold_closure_and_observed_transition_neighbors',
    context_note:'La cola completa exige cierre de contexto. Una cabecera QNode verificada puede estimarse individualmente antes de la línea inferida, conservando context_incomplete e incompatibilidad; sin esa evidencia se conserva la pose fuente.',
    counts:{...diagnostics?.counts,active:records.length,visible,omitted:records.length-visible,omissionReasons:reasons,
      incompleteHoldContext:missingContext.length,
      unsupportedPosition:records.filter(r=>!r.visible && r.reason!=='spatial_filter').length}};
}
function diagnoseVehicle(vehicle,time=current) {
  const loaded=Number.isFinite(time) && time>=INITIAL && time<=FINAL && continuousReplay && continuousReplay.activeIndex===continuousReplay.indexAt(time);
  const records=(transitionTimelines.get(vehicle) || timelines.get(vehicle) || []),active=records.filter(r=>r.timestamps[0]<=time && time<r.timestamps[1]);
  const segment=active.length===1 ? active[0] : null;
  const prior=records.filter(r=>r.timestamps[1]<=time).at(-1),next=records.find(r=>r.timestamps[0]>time);
  const reference=segment || active[0] || prior || next,pair=segment ? transitionRecords.get(markerKey(segment)) : null;
  const saved=time===current ? visibilityRecords.get(vehicle) : null;
  const motion=segment ? motionAt(segment,time) : null;
  const lane=segment ? laneObservationAt(vehicle,segment.Link_ID,time) : null;
  const observedNext=segment && pair?.next && pair.next.vehicle===segment.vehicle &&
    pair.next.Replay_Journey_Key===segment.Replay_Journey_Key && pair.next.timestamps?.[0]===segment.timestamps[1] ? pair.next.Link_ID : null;
  const link=segment && visualLaneRenderer?.describe(segment.Link_ID);
  const diagnostics=getVisualDiagnostics(time),evaluated=diagnostics.records.find(r=>r.vehicle_id===vehicle);
  const conflictSample=diagnostics.sampleCollisions?.({vehicle_ids:[vehicle],limit:100});
  const trip=reference?.Trip;
  // Absence alone is not an arrival, a domain exit, or a QSim forced move.
  const intervalReason=Number.isFinite(trip?.Arrival) && time>=trip.Arrival ? 'arrived' :
    Number.isFinite(trip?.Departure) && time<trip.Departure ? 'before_departure' :
    Number.isFinite(trip?.Last_Observed_Time) && time>trip.Last_Observed_Time ? 'after_last_observation' : 'unknown_interval';
  const publicState=reference?.Trip?.Transit ? SimZ1ContinuousLoader.transitState(reference,time) : null;
  const reason=!loaded ? 'window_not_loaded' : evaluated?.reason ?? saved?.reason ?? (active.length>1 ? 'overlapping_intervals' :
    !segment ? publicState?.state ?? intervalReason : !motion.available ? 'motion_unavailable' : 'frame_not_evaluated');
  const nativeCenter=reason!=='reconstruction_pending' && motion?.available ? centerPosition(segment,motion.fraction) : null;
  const candidate=loaded ? evaluated?.position ?? saved?.marker?.position ?? null : null;
  return {...diagnosticProvenance(),person_id:reference?.Agent_ID ?? reference?.Trip?.Person_ID ?? null,
    vehicle_id:vehicle,trip_id:reference?.Trip?.Trip_ID ?? null,journey_key:reference?.Replay_Journey_Key ?? null,time,
    synthetic_incident:loaded && segment ? incidentEffects?.participant({...segment,Observed_Queue_ID:lane?.lane},time) ?? null : null,
    driver_id:reference?.Driver_ID ?? trip?.Driver_ID ?? null,transit:trip?.Transit ?? null,service_state:publicState,
    previous_link:(pair?.previous || prior)?.Link_ID ?? null,current_link:segment?.Link_ID ?? null,
    next_link:(pair?.next || next)?.Link_ID ?? null,lane:lane?.lane ?? null,visual_lane:evaluated?.lane ?? saved?.marker?.Visual_Lane_Index ?? null,
    position:loaded && evaluated?.visible ? evaluated.position : null,visible:Boolean(loaded && evaluated?.visible),reason,
    visual_diagnostic:evaluated ?? null,
    conflicts:conflictSample?.records ?? (diagnostics.collisions || []).filter(row=>row.vehicles.some(v=>v.vehicle_id===vehicle)),
    conflict_count:conflictSample?.total_matches ?? null,conflicts_truncated:conflictSample?.truncated ?? false,
    limitations:(diagnostics.limitations || []).filter(row=>row.vehicle_id===vehicle),
    candidate_position:candidate,native_center_position:nativeCenter,
    native_center_position_source:reason==='reconstruction_pending' ? 'unavailable_visual_reconstruction' : motion?.status==='observed_event_position' ? 'native_link_entry_at_exact_timestamp' : 'estimated_link_interpolation_from_recorded_interval',
    candidate_links:active.map(record=>record.Link_ID),
    spatial_evidence:spatialRenderer && segment ? {link_allowed:spatialRenderer.allowed.has(segment.Link_ID),
      native_axis_inside:nativeCenter ? spatialRenderer.contains(nativeCenter) : null,
      rendered_center_inside:candidate ? spatialRenderer.contains(candidate) : null} : null,
    queue_reason:evaluated?.queue_state ?? saved?.marker?.Visual_Queue_State ?? null,
    body_support:evaluated?.body_support ?? saved?.marker?.Visual_Body_Support ?? null,
    body_reconstruction:evaluated?.body_reconstruction ?? saved?.marker?.Visual_Body_Reconstruction ?? null,
    turn_clearance:evaluated?.turn_clearance ?? saved?.marker?.Visual_Queue_Turn_Clearance ?? null,
    lane_source:evaluated?.lane_source ?? saved?.marker?.Visual_Lane_Source ?? null,
    observed_lane_id:evaluated?.observed_lane_id ?? saved?.marker?.Observed_Queue_ID ?? null,
    longitudinal_station_m:evaluated?.longitudinal_station_m ?? null,
    display_link:evaluated?.display_link ?? saved?.marker?.Visual_Queue_Display_Link_ID ?? segment?.Link_ID ?? null,
    display_station_m:evaluated?.display_station_m ?? null,
    native_queue_extent:evaluated?.native_queue_extent ?? null,
    queue_extent_projection:evaluated?.queue_extent_projection ?? null,
    head_stop_projection:evaluated?.head_stop_projection ?? null,
    native_occupancy:evaluated?.native_occupancy ?? segment?.Native_Occupancy ?? null,
    native_occupancy_progress:(evaluated?.native_occupancy_progress ?? segment?.Native_Occupancy_Progress ?? [])
      .filter(record=>record.time<=time),
    occupancy_domain:evaluated?.occupancy_domain ?? null,
    occupancy_reference:evaluated?.occupancy_reference ?? null,
    occupancy_release_projection:saved?.marker?.Visual_Occupancy_Release_Projection ?? null,
    facility_boundary_projection:evaluated?.facility_boundary_projection ?? saved?.marker?.Visual_Facility_Boundary_Projection ?? null,
    stop_boundary:evaluated?.stop_boundary ?? saved?.marker?.Visual_Queue_Stop_Boundary ?? null,
    stop_clearance_m:evaluated?.stop_clearance_m ?? saved?.marker?.Visual_Queue_Stop_Clearance_Meters ?? null,
    signal_controls:segment ? signalControlEvidence(segment.Link_ID,lane?.lane,observedNext,time) : [],
    dimension_contract:evaluated?.dimension_contract ? {...evaluated.dimension_contract,
      picking_tolerance:{units:'css_pixels_from_body_edge',mouse:SimZ1VehiclePicking.radius('mouse'),
        touch:SimZ1VehiclePicking.radius('touch'),changes_metric_body:false}} : null,
    interval:segment?.timestamps ?? null,link_length_m:link?.length_m ?? null,
    short_link:Boolean(link && link.length_m<(evaluated?.dimensions_m?.[0] ?? saved?.marker?.Visual_Body_Length_Meters ??
      (reference && typeof SimZ1VehicleCatalog==='function' ? SimZ1VehicleCatalog.resolve(reference).dimensions?.length_m : null) ?? 0)),
    stop_margin_m:evaluated?.stop_margin_m ?? saved?.marker?.Visual_Queue_Stop_Margin_Meters ?? null,
    stop_line_m:evaluated?.stop_line_m ?? saved?.marker?.Visual_Queue_Stop_Line_Meters ?? null,
    stop_line_source:evaluated?.stop_line_source ?? saved?.marker?.Visual_Queue_Stop_Line_Source ?? null,
    spacing_compatible:evaluated?.spacing_compatible ?? saved?.marker?.Visual_Queue_Compatible ?? null,
    qsim_forced_movement:{status:'not_available_in_replay',
      note:'Un conflicto visual o distance_exceeds_speed_cap no acredita FORCE. Requiere evento nativo simz1NativeDecision decision=FORCE.'},
    reduced_stop_margin:Boolean(saved?.marker?.Visual_Queue_Reduced_Margin),
    heading_degrees:evaluated?.heading ?? saved?.marker?.Visual_Body_Heading_Degrees ?? null,
    dimensions_m:evaluated?.dimensions_m ?? null,
    vehicle_presentation:reference && typeof SimZ1VehicleCatalog==='function' ? SimZ1VehicleCatalog.resolve(reference) : null,
    representation_envelope:evaluated?.envelope ?? saved?.marker?.Visual_Safety_Envelope ?? null,
    transition_before:pair?.previous ? (pair.previous.timestamps[1]===segment.timestamps[0] ? 'contiguous_events' : 'time_gap') : 'no_context',
    transition_after:pair?.next ? (segment.timestamps[1]===pair.next.timestamps[0] ? 'contiguous_events' : 'time_gap') : 'no_context',
    motion_reason:motion?.fallback_reason ?? null,buffering:continuousPendingTime!=null,displayed_time:lastRenderedTime};
}
let motionUnavailableCount=0;
let lastPointerType = 'mouse';
let lastRenderedTime=null, lastRenderedPaused=null, lastRenderedSpeed=null;
let lastSignalKey=null;
function markerKey(marker) {return continuousMode ? SimZ1ContinuousLoader.recordKey(marker) :
  JSON.stringify([marker.vehicle,marker.Link_ID,...marker.timestamps]);}
function queueStateLabel(state) {
  return ({forming:'formacion estimada',queued:'espaciado inferido durante la espera',releasing:'liberacion visual estimada',
    reconstruction_pending:'Posición no disponible / reconstrucción pendiente',
    storage_exceeded:'sin espacio geometrico dentro del enlace/carril',boundary_transition:'transicion en el limite representable',
    overlapping_release:'separacion no representable durante liberacion simultanea',
    geometry_or_lane_unavailable:'geometria o carril sin respaldo',body_geometry_unavailable:'cuerpo sin geometria representable',
    recorded_path_lateral_unknown:'trayectoria de fuente conservada; posicion lateral y espacio de cola desconocidos',
    body_unrepresentable:'posicion u orientacion sin geometria suficiente',following:'separacion visual de seguimiento',
    queue_context_incomplete:'contexto insuficiente para reconstruir la cola',
    native_facility_position:'centro nativo de parada; orientacion local estimada',
    native_link_entry_position:'entrada nativa en este instante; velocidad no observada',
    native_facility_body_exceeds_link:'centro nativo de parada; cuerpo visual excede el enlace',
    queue_projection_reverses_motion:'enlace corto: la proyeccion de cola exigiria retroceder',
    shared_upstream_queue_position_unknown:'cola compartida observada; posicion lateral y espacio no determinados',
    native_queue_extent_unknown:'cola observada sin dominio longitudinal inequívoco',
    body_overlap:'cuerpos sin separacion representable en esta geometria'})[state] || state;
}
function visualQueueText(marker) {
  if(!marker.Visual_Queue_Source) return marker.Visual_Queue_Representable===false ?
    '\nCuerpo visual no representable: '+queueStateLabel(marker.Visual_Queue_State || 'geometria insuficiente') : '';
  return '\nCola visual: '+queueStateLabel(marker.Visual_Queue_State || 'espaciado inferido')+
    '\nEspaciado/orden inferidos; eventos y velocidades fuente sin cambios'+
    (marker.Visual_Body_Reconstruction ? '\nCuerpo reconstruido desde frente y recorrido de carril; coordenadas estimadas, dimensiones conservadas' : '')+
    (Number.isFinite(marker.Visual_Queue_Entry_Seconds) ? '\nReferencia de orden: entrada '+
      (marker.Visual_Queue_Order_Source==='native_lane_entry' ? 'nativa al carril' : 'al enlace (respaldo estimado)')+
      ' a '+marker.Visual_Queue_Entry_Seconds+' s' : '')+
    (Number.isFinite(marker.Visual_Queue_Offset_Meters) ? '\nSeparacion longitudinal visual del eje interpolado: '+marker.Visual_Queue_Offset_Meters.toFixed(2)+' m' : '')+
    (marker.Visual_Queue_Reduced_Margin ? '\nMargen visual reducido: enlace corto; cuerpo conservado dentro de la geometria disponible' : '')+
    (marker.Visual_Queue_Compatible===false ? '\nIncompatibilidad sin resolver; cuerpo fuente conservado visible' : '')+
    (marker.Visual_Queue_Representable===false ? '\nMarcador omitido: no hay posicion representable dentro del enlace' : '');
}
function setQueueGap(value) {
  if(!Number.isFinite(value) || value<.1 || value>10)throw new Error('Espacio visual admitido: 0.10..10 m');
  if(certifiedQueueSettings && value!==certifiedQueueSettings.gap_m)
    throw new Error('El margen difiere de la reconstruccion verificada; prepare el soporte con el valor solicitado.');
  queueGapMeters=value;
  if(visualQueueRenderer)visualQueueRenderer.configure({gap_m:value});
  lastMarkerTime=null;render();
}
function setSafetyEnvelope(settings) {
  if(!visualQueueRenderer)throw new Error('Geometria visual no disponible');
  const allowed=['gap_m','lateral_clearance_m'];
  if(!settings || Object.keys(settings).some(key=>!allowed.includes(key)))throw new Error('Solo gap_m y lateral_clearance_m');
  if(certifiedQueueSettings && Object.keys(settings).some(key=>settings[key]!==certifiedQueueSettings[key]))
    throw new Error('Los margenes difieren de la reconstruccion verificada; prepare el soporte con los valores solicitados.');
  visualQueueRenderer.configure(settings);queueGapMeters=visualQueueRenderer.settings.gap_m;
  lastMarkerTime=null;render();
}

function clearSelection() {
  pinned=null;hovered=null;selectAgent(null);render();
}
function visibleInspection(object, hover=false) {
  if (!object) return null;
  if (object.vehicle) {
    const state=selectionAt(object,current);
    return state.visible && (!hover || state.active) ? object : null;
  }
  if (object.incident) return incidentActive(object,current) ? object : null;
  return object.system_id!=null || object.node ? object : null;
}
function inspectClickedObject(object) {
  // Inspecting a stop must not clear the pinned agent, its six fields or route.
  if(continuousMode && object?.transit_stop)return;
  // Repeated clicks on the same pending/loaded journey must not query SQLite again.
  if(continuousMode && object?.vehicle && object.vehicle===pinned?.vehicle && tripKey(object)===tripKey(pinned)) {
    selectionRequests.cacheHits++;
    hovered=null;refreshVehicleHighlights(true);updateVehicleCard();return;
  }
  hovered=null;pinned=object || null;selectAgent(pinned);render();
}
function inspectPointer(info,event) {
  const object=info?.object;
  // Signals/incidents retain their native selection. Vehicle picking uses the
  // projected CURRENT rigid bodies, with a CSS-pixel aperture outside them.
  if(!continuousMode || typeof SimZ1VehiclePicking!=='function' || object && !object.vehicle) return object || null;
  const viewport=info?.viewport || currentDeckViewport();
  if(!viewport?.project || !Number.isFinite(info?.x) || !Number.isFinite(info?.y)) return object || null;
  const pointerType=event?.pointerType || event?.srcEvent?.pointerType || lastPointerType;
  const markers=layers.find(layer=>layer.id==='trips')?.props.data || [];
  return SimZ1VehiclePicking.pick(markers,{x:info.x,y:info.y,width:viewport.width,height:viewport.height,
    pointerType,project:position=>viewport.project(position)})?.object || null;
}
// deck.gl 9.1.14: MapController supports dragMode. Deck routes both click and
// dblclick through onClick; its single-tap recognizer requires double-tap failure.
// See @deck.gl/core@9.1.14/dist/lib/constants.js and controllers/controller.js.
// Use that single gesture pipeline, with no DOM click/dblclick listeners/timers.
let cameraMode='pan',cameraDragging=false,cameraDragConsumed=false;
let cameraViewState=continuousMode ? {...config.initialViewState,minPitch:0,maxPitch:60,
  pitch:Number.isFinite(config.initialViewState?.pitch) ? Math.max(0,Math.min(60,config.initialViewState.pitch)) : 0,
  bearing:Number.isFinite(config.initialViewState?.bearing) ? config.initialViewState.bearing : 0} : null;
let mapLabelSignature=null,mapLabelView=null;
function currentDeckViewport() {
  // deck.gl 9.1.14 getViewports() asserts viewManager, which is created
  // asynchronously. Optional chaining on the method does not guard readiness.
  if(deckInstance.isInitialized===false)return null;
  return deckInstance.getViewports?.()?.[0] ?? null;
}
function refreshSignalView(size=null) {
  if(!continuousMode || typeof signalGeometry==='undefined')return;
  const currentViewport=currentDeckViewport();
  if(!currentViewport)return;
  const {width,height}=size || currentViewport;
  const viewport=new deck.WebMercatorViewport({...cameraViewState,width,height});
  const began=performance.now(),old=layers;
  layers=signalGeometry.updateLayers(layers,viewport);
  featureWork.signalViewCalls++;featureWork.signalViewUpdates+=old!==layers ? 1 : 0;
  featureWork.signalViewCpuMs+=performance.now()-began;
}
function refreshMapLabels(size=null) {
  if(!continuousMode || !visualLaneRenderer || !layers.some(layer=>layer.id==='map-labels'))return;
  if(mapLabelSignature!=null && mapLabelView===cameraViewState && size==null)return;
  try {
    const currentViewport=currentDeckViewport();
    if(!currentViewport)return;
    const {width,height}=size || currentViewport;
    const signature=JSON.stringify([cameraViewState,width,height]);
    if(signature===mapLabelSignature){mapLabelView=cameraViewState;return;}
    const viewport=typeof deck!=='undefined' && deck.WebMercatorViewport ?
      new deck.WebMercatorViewport({...cameraViewState,width,height}) : currentViewport;
    const labels=visualLaneRenderer.labels(cameraViewState,p=>viewport.project(p),width,height,
      p=>!spatialRenderer || spatialRenderer.contains(p),spatialRenderer?.allowed);
    layers=layers.map(layer=>layer.id==='map-labels' ? layer.clone({data:labels}) : layer);
    mapLabelSignature=signature;mapLabelView=cameraViewState;renderCounters.labelBuilds++;
  } catch(error) {
    // Labels are optional. Quarantine only this layer until reload; keep the
    // validated replay, controls and original diagnostic available.
    layers=layers.filter(layer=>layer.id!=='map-labels');
    reportViewerError(error,'etiquetas del mapa');
  }
}
function cameraControllerOptions() {
  return {dragMode:cameraMode,dragPan:cameraMode==='pan',dragRotate:cameraMode==='rotate',
    doubleClickZoom:false,scrollZoom:true,touchZoom:true,touchRotate:false,inertia:false};
}
function setCameraMode(mode) {
  if(!continuousMode || mode===cameraMode)return;
  cameraMode=mode;
  deckInstance.setProps({controller:cameraControllerOptions()});
  describeCameraMode();
}
function describeCameraMode() {
  const canvas=deckInstance.getCanvas?.();
  if(!canvas)return;
  const label=cameraMode==='rotate' ? 'ROTAR: arrastre para girar e inclinar; clic en el fondo o Escape para desplazar.' :
    'DESPLAZAR: arrastre para mover; rueda para zoom; doble clic en el fondo para rotar.';
  canvas.title=label;canvas.setAttribute('aria-label',label);
}
function updateCameraViewState({viewState}) {
  if(!['longitude','latitude','zoom','pitch','bearing'].every(key=>Number.isFinite(viewState[key])))return cameraViewState;
  cameraViewState={...viewState,minPitch:0,maxPitch:60,pitch:Math.max(0,Math.min(60,viewState.pitch))};
  deckInstance.setProps({viewState:cameraViewState});
  refreshMapLabels();
  refreshSignalView();
  if(typeof transitStops!=='undefined') {
    const began=performance.now(),old=layers;
    layers=transitStops.updateLayers(layers,cameraViewState.zoom);
    featureWork.stopZoomCalls++;featureWork.stopLayerUpdates+=layers!==old ? 1 : 0;
    featureWork.stopZoomCpuMs+=performance.now()-began;
  }
  if(continuousMode){hovered=null;refreshVehicleHighlights();updateVehicleCard();}
  deckInstance.setProps({layers});
  return cameraViewState;
}
function inspectCameraClick(info,event) {
  if(cameraDragging || cameraDragConsumed)return;
  const object=inspectPointer(info,event);
  if(event?.type==='dblclick' || event?.tapCount===2) {
    if(!object)setCameraMode('rotate');
    return;
  }
  if(!object)setCameraMode('pan');
  inspectClickedObject(object);
}
const originalDeckOnLoad=deckInstance.props?.onLoad;
const originalBeforeRender=deckInstance.props?.onBeforeRender,originalAfterRender=deckInstance.props?.onAfterRender;
const markerPosition=object=>object.position;
deckInstance.setProps({
  getTooltip: continuousMode ? info=>cameraDragging ? null :
    (typeof signalGeometry!=='undefined' ? signalGeometry.tooltip(info.object,signalStateAt,current) : null) ||
    (typeof transitStops!=='undefined' ? SimZ1TransitStops.tooltip(info.object) : null) : null,
  onHover: continuousMode ? hoverVehicleCard : (info,event) => { if(cameraDragging)return;hovered = inspectPointer(info,event); render(); },
  onClick: continuousMode ? inspectCameraClick : (info,event) => inspectClickedObject(inspectPointer(info,event)),
  ...(continuousMode ? {
    onBeforeRender:context=>{deckDrawStart=performance.now();originalBeforeRender?.(context);},
    onAfterRender:context=>{lastDeckDrawCpuMs=performance.now()-deckDrawStart;renderCounters.draws++;originalAfterRender?.(context);},
    onLoad:()=>{originalDeckOnLoad?.();mapLabelSignature=null;refreshSignalView();deckInstance.setProps({layers});render();},
    viewState:cameraViewState,controller:cameraControllerOptions(),onViewStateChange:updateCameraViewState,
    onResize:size=>{
      try {
        mapLabelSignature=null;refreshMapLabels(size);
        refreshSignalView(size);
        hovered=null;refreshVehicleHighlights();updateVehicleCard();
        deckInstance.setProps({layers});positionVehicleCard();
      }
      catch(error) { reportViewerError(error,'redimensionar mapa'); }
    },
    getCursor:({isDragging})=>isDragging ? 'grabbing' : cameraMode==='rotate' ? 'crosshair' : 'grab',
    onDragStart:()=>{cameraDragging=true;cameraDragConsumed=true;hovered=null;refreshVehicleHighlights(true);updateVehicleCard();},
    onDragEnd:()=>{cameraDragging=false;}
  } : {})
});
if(continuousMode) {
  describeCameraMode();
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){setCameraMode('pan');clearSelection();}});
  const canvas=deckInstance.getCanvas?.();
  if(canvas)canvas.onpointerleave=()=>{hovered=null;vehicleCardPointer=null;refreshVehicleHighlights(true);updateVehicleCard();};
}
document.addEventListener('pointerdown', event => {
  const canvas=deckInstance.getCanvas?.();
  if(canvas?.contains?.(event.target)) {
    lastPointerType=event.pointerType || 'mouse';cameraDragConsumed=false;
  }
  // Timeline/buttons are controls for the selected trip, so seeking preserves
  // its identity. A click elsewhere explicitly clears both pin and hover.
  if (canvas?.contains?.(event.target) || hud.contains?.(event.target) || showBar?.contains?.(event.target) || info.contains?.(event.target) || vehicleCard?.contains?.(event.target) || runPanel?.contains?.(event.target)) return;
  clearSelection();
});
function render(timestamp=performance.now()) {
  if(!continuousMode)return renderFrame();
  // Immediate controls/camera draws also start a new cadence interval. RAF may
  // observe the same native time, so it cannot be the only owner of this clock.
  try { renderFrame();lastDrawTimestamp=timestamp; }
  catch(error) {
    lastMarkerTime=null;selectionChanged=true; // Retry a complete frame next time.
    reportViewerError(error,'render');
  }
}
function renderFrame() {
  const renderStarted=performance.now();let markerMs=0,queueMs=0,deckMs=0;
  let phaseAt=renderStarted;const stages={},beforeCounters={...renderCounters};
  const stage=name=>{const end=performance.now();stages[name]=end-phaseAt;phaseAt=end;};
  refreshMapLabels();
  stage('labelsMs');
  const activeIncidents = incidents.filter(incident => incidentActive(incident,current) && (!spatialRenderer || spatialRenderer.contains(incident.position)));
  const nextIncidentKey = activeIncidents.map(incident => incident.Link_ID + ':' + incident.start).join('|');
  stage('incidentsMs');
  const signalKey=signalFrameKey(current);
  const updateSignals = lastSignalTime==null || lastSignalKey!==signalKey || lastSignalSource!==signalTimelines;
  // Loading a window while paused can replace UNKNOWN by a native state at
  // the SAME clock value. deck.gl accessors need a changed update trigger too.
  if(updateSignals)signalRenderRevision++;
  stage('signalsMs');
  const frameTime = current;
  const updateMarkers = lastMarkerTime !== current;
  if (!continuousMode && updateMarkers && hovered?.vehicle) hovered=null;
  hovered=visibleInspection(hovered,true);
  let markers = [];
  if (updateMarkers) {
    activePublicVehicleCount=0;
    const markersStarted=performance.now();
    motionUnavailableCount=0;
    visibilityRecords=new Map();
    const activeAgents = new Set();
    const activeByVehicle=new Map();
    for(const record of activeRecordsAt(current)) {
      if(continuousMode && record.Trip?.Departure>=FINAL)continue;
      if(activeByVehicle.has(record.vehicle)) {
        activeByVehicle.set(record.vehicle,null);visibilityRecords.set(record.vehicle,{visible:false,reason:'overlapping_intervals'});
      } else activeByVehicle.set(record.vehicle,record);
    }
    stage('activeIndexMs');
    for (const segment of activeByVehicle.values()) {
        if(!segment){motionUnavailableCount++;continue;}
        if(segment.Trip?.Transit)activePublicVehicleCount++;
        const marker=markerAt(segment,current);
        if (!marker) {motionUnavailableCount++;visibilityRecords.set(segment.vehicle,{visible:false,reason:reconstructionPending(segment) ? 'reconstruction_pending' : 'motion_unavailable',segment,
          motion_reason:motionAt(segment,current).fallback_reason});continue;}
        markers.push(marker);
        if(segment.Agent_ID != null) activeAgents.add(segment.Agent_ID);
    }
    markerMs=performance.now()-markersStarted;
    stage('motionAndMarkersMs');
    if(visualQueueRenderer) {
      const queuesStarted=performance.now();
      const frame=visualQueueRenderer.frame(markers,current,transitionNeighbors,queueRoster());
      queueMs=performance.now()-queuesStarted;
      markers=frame.markers;visualQueueCounts=frame.counts;
      visualFrameDiagnostics=frame.diagnostics;
      visualQueueRecords=new Map();for(const rows of [markers,frame.omitted || []])for(const marker of rows)visualQueueRecords.set(markerKey(marker),marker);
      for(const marker of frame.omitted || [])visibilityRecords.set(marker.vehicle,{visible:false,reason:marker.Visual_Queue_State || 'geometry_unavailable',marker});
    } else if(partialVisualPolicy) {
      visualQueueRecords=new Map();
      markers=markers.filter(marker=>{
        if(marker.Visual_Queue_Context?.reason!=='reconstruction_pending')return true;
        const omitted={...marker,position:null,Visual_Body_Path:[],Visual_Queue_Representable:false,
          Visual_Queue_State:'reconstruction_pending',Visual_Queue_Source:'unavailable_visual_reconstruction'};
        visualQueueRecords.set(markerKey(marker),omitted);
        visibilityRecords.set(marker.vehicle,{visible:false,reason:'reconstruction_pending',marker:omitted});
        return false;
      });
    }
    stage('queuesMs');
    const incidentFrame=incidentEffects?.frame(markers,current);
    if(incidentFrame) {
      markers=incidentFrame.markers;emergencyAnnotations=incidentFrame.icons;
      if(incidentFrame.participant_count)for(const marker of markers)if(marker.Visual_Synthetic_Incident)
        visualQueueRecords.set(markerKey(marker),marker);
    }
    for(const marker of markers)visibilityRecords.set(marker.vehicle,{visible:true,
      reason:marker.Visual_Queue_Compatible===false ? marker.Visual_Queue_State : 'visible',marker});
    if(spatialRenderer) {
      const retained=spatialRenderer.markers(markers),visible=new Set(retained);
      for(const marker of markers)if(!visible.has(marker))visibilityRecords.set(marker.vehicle,{visible:false,reason:'spatial_filter',marker});
      markers=retained;
    }
    const diagnosticRecords=[...visibilityRecords].map(([vehicle,row])=>({vehicle_id:vehicle,time:current,
      visible:row.visible,reason:row.reason,link_id:row.marker?.Link_ID ?? null,lane:row.marker?.Visual_Lane_Index ?? null,
      synthetic_incident:row.marker?.Visual_Synthetic_Incident ?? null,
      position:row.marker?.position ?? null,heading:row.marker?.Visual_Body_Heading_Degrees ?? null,
      native_position:row.marker?.Visual_Native_Center_Position ?? null,
      spacing_compatible:row.marker?.Visual_Queue_Compatible ?? null,
      stop_line_m:row.marker?.Visual_Queue_Stop_Line_Meters ?? null,stop_line_source:row.marker?.Visual_Queue_Stop_Line_Source ?? null,
      dimensions_m:row.marker ? [row.marker.Visual_Body_Length_Meters,row.marker.Visual_Body_Width_Meters] : null,
      presentation:row.marker?.Visual_Vehicle_Presentation ?? null,envelope:row.marker?.Visual_Safety_Envelope ?? null,
      interval:row.marker?.timestamps ?? row.segment?.timestamps, motion_reason:row.motion_reason,
      source:row.marker?.Visual_Queue_Source ?? row.marker?.Position_Evidence,
      envelope:row.marker?.Visual_Safety_Envelope,queue_state:row.marker?.Visual_Queue_State,
      display_link:row.marker?.Visual_Queue_Display_Link_ID,details:row.marker?.Visual_Diagnostic,
      ...visualQueueRenderer?.describePose(row.marker)}));
    visualFrameDiagnostics=completeVisualDiagnostics(current,visualFrameDiagnostics,diagnosticRecords);
    activeAgentCount = activeAgents.size;
    const beforeUserFilter=markers.length;
    markers=markers.filter(visibleByUserChoice);
    filterStatus.textContent=typeFilter.value==='all' && !routeFilter.value.trim() ? 'Sin filtros' :
      'Filtro visible: '+markers.length+'/'+beforeUserFilter+'; totales nativos sin cambios';
    visibleMarkerCount = markers.length;
    visualLaneCounts = {estimatedMarkers:0,nativeMarkers:0,centerlineMarkers:0};
    for(const marker of markers) visualLaneCounts[(marker.Visual_Lane_Source==='native' ? 'native' :
      marker.Visual_Lane_Source==='estimated' ? 'estimated' : 'centerline')+'Markers']++;
    lastMarkerTime = current;
  }
  stage('visibilityDiagnosticsMs');
  const selection = selectionAt(pinned,current,selectedHistory);
  const updateSelection = updateMarkers || selectionChanged;
  const route = updateSelection ? (selection.visible ? splitSelectedRoute(selectedHistory,current) : {history:[],future:[],unresolved:[]}) : null;
  const endpoints=selection.visible ? selectedEndpoints : [];
  if(routeLegend && route)routeLegend.hidden=!(route.history.length || route.future.length || route.unresolved?.length || selectedItinerary.length);
  stage('selectionMs');
  // Independent wall-clock annotations: active markers, queues, collision
  // diagnostics and the six-field card never consume these rows.
  const arrivalAnnotations=arrivalEffects?.frame() || [];
  const oldLayers=layers;let changedLayers=false;
  layers = layers.map(layer => {
    if(layer.id==='selected-itinerary' && updateSelection && layer.props.data!==selectedItinerary)return layer.clone({data:selectedItinerary});
    if(layer.id==='selected-unresolved' && route)return layer.clone({data:route.unresolved || []});
    if(layer.id==='synthetic-incident-emergency' && updateMarkers && (emergencyAnnotations.length || layer.props.data?.length))
      return layer.clone({data:emergencyAnnotations.filter(row=>!spatialRenderer || spatialRenderer.contains(row.position))});
    if(layer.id==='arrival-annotations' && (arrivalAnnotations.length || layer.props.data?.length))
      return layer.clone({data:arrivalAnnotations});
    if (['selected-history','selected-history-casing'].includes(layer.id) && route && (route.history.length || layer.props.data?.length)) return layer.clone({data:route.history});
    if (['selected-future','selected-future-casing'].includes(layer.id) && route && (route.future.length || layer.props.data?.length)) return layer.clone({data:route.future});
    if (layer.id === 'selected-origin' && updateSelection && (endpoints.length || layer.props.data?.length)) return layer.clone({data:endpoints.filter(p=>p.kind==='origin')});
    if (layer.id === 'selected-destination' && updateSelection && (endpoints.length || layer.props.data?.length)) return layer.clone({data:endpoints.filter(p=>p.kind==='destination')});
    if (layer.id === 'incidents' && nextIncidentKey !== incidentKey) return layer.clone({data:activeIncidents,visible:true});
    if (layer.id === 'trips' && updateMarkers) {
      const old=layer.props.data;
      if(old?.length===markers.length && markers.every((marker,i)=>marker===old[i]))return layer;
      renderCounters.tripLayerUpdates++;return layer.clone({data: markers, visible: true, getPosition: markerPosition});
    }
    if(continuousMode && updateSignals && typeof SimZ1SignalGeometry==='function') {
      const began=performance.now();
      const props=SimZ1SignalGeometry.stateProps(layer.id,signalStateAt,frameTime,signalRenderRevision);
      if(props) {
        const changed=layer.clone({...props,updateTriggers:{...layer.props.updateTriggers,...props.updateTriggers}});featureWork.signalLayerUpdates++;
        featureWork.signalPropsCpuMs+=performance.now()-began;return changed;
      }
    }
    if (layer.id === 'signals' && !layer.props.mesh && updateSignals) return layer.clone({
      getIcon: object => signalIcon(object,frameTime), updateTriggers: {getIcon:[frameTime,signalRenderRevision]}
    });
    return layer;
  });
  if(continuousMode){checkVehicleHover();refreshVehicleHighlights();}
  changedLayers=layers.some((layer,i)=>layer!==oldLayers[i]);if(!changedLayers)layers=oldLayers;
  stage('layersMs');
  const deckStarted=performance.now();
  if(changedLayers){deckInstance.setProps({layers});renderCounters.deckSubmissions++;}
  arrivalAnnotationsDrawn=arrivalAnnotations.length>0;
  deckMs=performance.now()-deckStarted;stage('deckSubmitMs');
  selectionChanged = false;
  lastSignalTime = current;
  lastSignalKey = signalKey;
  lastSignalSource = signalTimelines;
  incidentKey = nextIncidentKey;
  const timeLabel = formatClock(current);
  if(cameraCountsLabel) {
    const drawn=layers.find(layer=>layer.id==='trips')?.props.data || [],viewport=currentDeckViewport();
    let inside=0;
    if(viewport?.project)for(const marker of drawn) {
      const p=viewport.project(markerPosition(marker));
      if(p[0]>=0 && p[0]<=viewport.width && p[1]>=0 && p[1]<=viewport.height)inside++;
    }
    cameraCountsLabel.textContent='Vehículos con intervalo en la fuente cargada: '+visibilityRecords.size+
      ' · Posiciones representables antes de filtros: '+(visualFrameDiagnostics?.counts.visible ?? 0)+
      ' · Marcadores dibujados: '+visibleMarkerCount+' · Centros en cámara: '+(viewport?inside:'—')+
      ' · Fuera de cámara: '+(viewport?drawn.length-inside:'—')+' (sin medir oclusión).';
  }
  const clockText = continuousMode ? 'Hora simulada '+timeLabel.replace(' (cierre del dia)','').replace(' (fin de observación)','')+
    ' | Dibujados '+(continuousReplay?.activeIndex==null ? '—' : visibleMarkerCount)+' | '+speed+'x' :
    timeLabel + ' | Agentes activos visibles: ' + activeAgentCount.toLocaleString('en-US') +
    ' | ' + speed + 'x' + (paused ? ' | Pausa' : '');
  if(clock.textContent!==clockText)clock.textContent=clockText;
  clock.title=timeLabel+(paused ? ' | Pausa' : '');
  if(queueStatus) queueStatus.textContent='Colas visuales; espaciado inferido\nColocados: '+visualQueueCounts.positioned+
    ' | Desborde: '+visualQueueCounts.overflow+' | Sin redistribucion: '+visualQueueCounts.unrepresentable+
    ' | Conflictos detectados: '+(visualQueueCounts.overlapsDetected || 0)+
    ' | Sin resolver: '+(visualQueueCounts.unresolvedOverlaps || 0)+
    ' | Cuerpos conservados con incompatibilidad: '+(visualQueueCounts.incompatiblePosition || 0)+
    '\nTramos con demora registrada sin posicion: '+visualQueueCounts.unknownPositionWait+
    '\nOtros cuerpos no representables: '+(visualQueueCounts.bodyUnrepresentable || 0)+
    ' | Movimiento no representable: '+motionUnavailableCount+
    '\nVehículos con intervalo en la fuente cargada: '+(visualFrameDiagnostics?.counts.active ?? 0)+
    ' | Posiciones representables antes de filtros: '+(visualFrameDiagnostics?.counts.visible ?? 0)+
    ' | Dibujados: '+visibleMarkerCount+
    ' | Omitidos: '+(visualFrameDiagnostics?.counts.omitted ?? 0)+
    '\nMotivos de omision: '+JSON.stringify(visualFrameDiagnostics?.counts.omissionReasons ?? {})+
    '\nIncompatibilidades: '+JSON.stringify(visualQueueCounts.warningReasons ?? {});
  seeker.value = continuousMode && continuousPendingTime!=null ? continuousPendingTime : current;
  seeker.setAttribute('aria-valuetext',continuousMode && continuousPendingTime!=null ? formatClock(continuousPendingTime)+'; cargando' : timeLabel);
  realtime.setAttribute('aria-pressed',String(speed === 1));
  original.setAttribute('aria-pressed',String(speed === SPEED));
  realtime.style.background = speed === 1 ? '#a8d5ff' : '';
  original.style.background = speed === SPEED ? '#a8d5ff' : '';
  updateTechnicalInspection();
  if(continuousMode)updateVehicleCard();
  if (journeyRetry) journeyRetry.hidden=!(pinned?.vehicle && selectionJourneyStatus?.key===tripKey(pinned) &&
    selectionJourneyStatus.state==='unavailable');
  if(journeyStatus) {
    journeyStatus.hidden=!pinned?.vehicle || !['loading','retrying','unavailable'].includes(selectionJourneyStatus?.state);
    journeyStatus.textContent=journeyStatus.hidden ? '' : selectionJourneyStatus.state==='loading' ?
      'Consultando recorrido completo...' : selectionJourneyStatus.message;
  }
  lastRenderedTime=current;lastRenderedPaused=paused;lastRenderedSpeed=speed;
  stage('uiMs');
  if(continuousMode) {
    const sample={time:current,index:continuousReplay?.activeIndex,speed,renderMs:performance.now()-renderStarted,
      markerMs,queueMs,deckSubmitMs:deckMs,stages,queueProfile:updateMarkers ? visualQueueRenderer?.profile : null,
      allocations:{markerObjects:renderCounters.markerCreates-beforeCounters.markerCreates,markerReuses:renderCounters.markerReuses-beforeCounters.markerReuses},
      tripLayerUpdates:renderCounters.tripLayerUpdates-beforeCounters.tripLayerUpdates,changedLayers,
      dataUpdated:updateMarkers,wallTime:performance.now(),visible:visibleMarkerCount,firstAfterActivation:firstWindowFrame!=null};
    if(firstWindowFrame!=null){sample.activationToFrameMs=performance.now()-firstWindowFrame;firstWindowFrame=null;}
    continuousPerformance.frames.push(sample);if(continuousPerformance.frames.length>600)continuousPerformance.frames.shift();
  }
}
function advance(timestamp) {
  if (previous !== null && !paused && !document.hidden && continuousPendingTime==null && timestamp > previous) {
    const next=current+(timestamp-previous)/1000*speed;
    if (continuousMode) {
      requestContinuousTime(Math.min(FINAL,next));
      if (current>=FINAL) {paused=true;toggle.textContent='Reproducir';}
    } else if (config.pagination) {
      current=Math.min(LAST_REPLAY_INSTANT,next);
      if (next>=FINAL) { paused=true;toggle.textContent='Reproducir'; }
    } else current=INITIAL+((next-INITIAL)%(FINAL-INITIAL));
  }
  previous = timestamp;
}
toggle.onclick = () => { advance(performance.now()); paused = continuousMode && (continuousPendingTime ?? current)>=FINAL || !paused; toggle.textContent = paused ? 'Reproducir' : 'Pausar'; render(); };
function setSpeed(value) { advance(performance.now()); speed = value; render(); }
realtime.onclick = () => setSpeed(1);
original.onclick = () => setSpeed(SPEED);
seeker.oninput = () => {
  const requested = Number(seeker.value);
  if (!Number.isFinite(requested)) return;
  if (continuousMode) {requestContinuousTime(Math.max(INITIAL,Math.min(FINAL,requested)),true);return;}
  current = Math.max(INITIAL,Math.min(LAST_REPLAY_INSTANT,requested));
  if (config.pagination && requested>=FINAL) { paused=true;toggle.textContent='Reproducir'; }
  previous = performance.now();
  render();
};
function animate(timestamp) {
  if(lastAnimationTimestamp!=null) {
    continuousPerformance.lastFrameGapMs=timestamp-lastAnimationTimestamp;
    continuousPerformance.maxFrameGapMs=Math.max(continuousPerformance.maxFrameGapMs,continuousPerformance.lastFrameGapMs);
  }
  lastAnimationTimestamp=timestamp;
  try {
    const arrivalsBefore=arrivalEffects?.triggered;
    advance(timestamp);
    if(continuousMode && continuousPendingTime!=null)updateContinuousStatus();
    const urgent=paused!==lastRenderedPaused || speed!==lastRenderedSpeed || selectionChanged ||
      arrivalEffects?.triggered!==arrivalsBefore ||
      arrivalEffects?.expiryDue() || arrivalAnnotationsDrawn && !arrivalEffects?.needsFrame();
    // Advance the native clock every RAF; coalesce drawing on high-refresh
    // displays. A newly crossed arrival must publish its marker immediately:
    // its 5000 ms wall clock has already started, even inside the draw interval.
    // Seeks/buttons/camera still render immediately, without a backlog.
    if (!continuousMode || urgent || (current!==lastRenderedTime || arrivalEffects?.needsFrame() || arrivalAnnotationsDrawn) &&
        timestamp-lastDrawTimestamp>=1000/maxDrawHz-.1) {
      render(timestamp);
    }
  } catch(error) {
    if(!continuousMode)throw error;
    reportViewerError(error,'animacion');
  } finally { requestAnimationFrame(animate); }
}
async function preparationYield(signal) {
  if(signal?.aborted)throw Object.assign(new Error('Preparacion cancelada'),{name:'AbortError'});
  await new Promise(resolve=>setTimeout(resolve,0));
  if(signal?.aborted)throw Object.assign(new Error('Preparacion cancelada'),{name:'AbortError'});
}
async function validateSpatialPayload(payload,signal) {
  if(!spatialRenderer)return;
  let count=0;
  // Trip metadata is shared by many segments. Validate each identity once.
  for(const trip of new Set([...Object.values(payload.trips),...Object.values(payload.queue_context?.trips || {})])) {
    spatialRenderer.validateTrip(trip);
    if(++count%512===0)await preparationYield(signal);
  }
  for(const record of [...payload.segments,...(payload.context_segments || []),...(payload.queue_context?.segments || []),
      ...(payload.queue_context?.transition_segments || [])]) {
    if(!spatialRenderer.allowed.has(record.Link_ID))throw new Error('Tramo fuera de los enlaces espaciales validados');
    if(++count%512===0)await preparationYield(signal);
  }
}
async function preparePartialAvailability(prepared,signal) {
  if(!partialVisualPolicy)return;
  // Unknown bodies are never removed as obstacles while their neighbours keep
  // a newly valid slot. Bound possible support by the whole recorded path,
  // its available contiguous chain and every referenced native corridor part.
  // This is a local conservative omission graph, not a causal reconstruction.
  const keyOf=r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key ?? '',r.Link_ID,r.timestamps]);
  const rows=new Map([...prepared.transitionTimelines.values()].flat().map(r=>[keyOf(r),r]));
  const domains=new Map(),cells=new Map(),corridors=new Map(),unknown=new Set(),memberships=new Map(),cellSize=64;
  const project=point=>[(point[0]-(visualLaneRenderer?.projection?.origin?.[0] ?? 0))*(visualLaneRenderer?.projection?.xScale ?? 111195),
    (point[1]-(visualLaneRenderer?.projection?.origin?.[1] ?? 0))*(visualLaneRenderer?.projection?.yScale ?? 111195)];
  const add=(map,key,member)=>{if(!map.has(key))map.set(key,new Set());map.get(key).add(member);};
  const eachCell=(box,fn)=>{
    const x0=Math.floor(box.minX/cellSize),x1=Math.floor(box.maxX/cellSize),
      y0=Math.floor(box.minY/cellSize),y1=Math.floor(box.maxY/cellSize);
    if((x1-x0+1)*(y1-y0+1)>1024)return false;
    for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++)fn(x+','+y);return true;
  };
  const linkMargins=new Map();
  const supportMargin=link=>{
    if(!link?.eligible || !link.geometry)return null;
    if(!linkMargins.has(link.id)) {
      let geometric=0;for(let lane=0;lane<link.lanes;lane++)geometric=Math.max(geometric,visualLaneRenderer.intersectionSetback(link.id,lane));
      linkMargins.set(link.id,(link.lanes+link.opposing)*link.width+geometric+
        (certifiedQueueSettings?.stop_line_setback_m ?? 2)+queueGapMeters);
    }
    return linkMargins.get(link.id);
  };
  let count=0;
  for(const [key,record] of rows) {
    const related=[record];
    const paths=[],supportLinks=new Set(),domain={minX:Infinity,minY:Infinity,maxX:-Infinity,maxY:-Infinity,corridors:new Set(),unknown:!visualLaneRenderer};
    let margin=0,bodyExtent=0;
    for(const r of related) {
      paths.push(r.path);
      const dimensions=SimZ1VehicleCatalog.resolve(r).dimensions,link=visualLaneRenderer?.links.get(r.Link_ID);
      if(!dimensions || !link?.geometry)domain.unknown=true;
      if(link)supportLinks.add(link);
      if(dimensions)bodyExtent=Math.max(bodyExtent,dimensions.length_m+dimensions.width_m);
      const occupancy=r.Native_Occupancy;
      if(occupancy?.policy==='corridor-length-v1') {
        domain.corridors.add(occupancy.corridor_id);
        const corridor=visualLaneRenderer?.occupancyCorridors.get(occupancy.corridor_id);
        if(!corridor)domain.unknown=true;
        else for(const part of corridor.parts){paths.push(part.link.data.path);supportLinks.add(part.link);}
        for(const id of [...(occupancy.exit_links || []),...(occupancy.passage_links || [])]) {
          const part=visualLaneRenderer?.links.get(id);if(!part?.geometry)domain.unknown=true;else {paths.push(part.data.path);supportLinks.add(part);}
        }
      }
    }
    for(const link of supportLinks) {
      const extra=supportMargin(link);if(!Number.isFinite(extra))domain.unknown=true;else margin=Math.max(margin,bodyExtent+extra);
    }
    for(const path of paths) {
      if(!Array.isArray(path) || path.length<2){domain.unknown=true;continue;}
      for(const point of path) {
        if(!Array.isArray(point) || !point.every(Number.isFinite)){domain.unknown=true;continue;}
        const [x,y]=project(point);domain.minX=Math.min(domain.minX,x-margin);domain.maxX=Math.max(domain.maxX,x+margin);
        domain.minY=Math.min(domain.minY,y-margin);domain.maxY=Math.max(domain.maxY,y+margin);
      }
    }
    if(!Number.isFinite(domain.minX))domain.unknown=true;
    domains.set(key,domain);
    if(++count%256===0)await preparationYield(signal);
  }
  const contiguous=record=>{
    const pair=prepared.transitionRecords.get(markerKey(record)) || {};
    return [pair.previous,pair.next].filter(r=>r && r.vehicle===record.vehicle && r.Replay_Journey_Key===record.Replay_Journey_Key &&
      (r.timestamps[1]===record.timestamps[0] || record.timestamps[1]===r.timestamps[0]));
  };
  // Rear release can recurse through previous corridors. Union the complete
  // available native chain before testing geographic exclusion, even when an
  // earlier interval's epoch differs. No unseen route or body pose is invented.
  const grouped=new Set();
  for(const [key] of rows) {
    if(grouped.has(key))continue;
    const component=[key],area={minX:Infinity,minY:Infinity,maxX:-Infinity,maxY:-Infinity,corridors:new Set(),unknown:false};
    grouped.add(key);
    for(let i=0;i<component.length;i++) {
      const member=component[i],part=domains.get(member);area.unknown ||= part.unknown;
      area.minX=Math.min(area.minX,part.minX);area.maxX=Math.max(area.maxX,part.maxX);
      area.minY=Math.min(area.minY,part.minY);area.maxY=Math.max(area.maxY,part.maxY);
      for(const corridor of part.corridors)area.corridors.add(corridor);
      for(const adjacent of contiguous(rows.get(member))) {
        const next=keyOf(adjacent);if(!grouped.has(next)){grouped.add(next);component.push(next);}
      }
      if(++count%256===0)await preparationYield(signal);
    }
    for(const member of component)domains.set(member,area);
  }
  for(const [key,domain] of domains) {
    const membership=[];memberships.set(key,membership);
    if(domain.unknown || !eachCell(domain,cell=>{add(cells,cell,key);membership.push(cell);}))unknown.add(key);
    for(const corridor of domain.corridors)add(corridors,corridor,key);
    if(++count%256===0)await preparationYield(signal);
  }
  const pending=[...prepared.queueContexts].filter(([,row])=>row.reason==='reconstruction_pending').map(([key])=>key),seen=new Set(pending),remaining=new Set(rows.keys());
  const removeFromIndex=key=>{
    remaining.delete(key);unknown.delete(key);
    for(const cell of memberships.get(key) || [])cells.get(cell)?.delete(key);
    for(const corridor of domains.get(key)?.corridors || [])corridors.get(corridor)?.delete(key);
  };
  for(const key of pending)removeFromIndex(key);
  const enqueue=(key,dependency,kind)=>{
    if(seen.has(key))return;
    if(prepared.queueContexts.get(key)?.complete===true && prepared.queueContextCheckpoints.get(key)?.final)return;
    seen.add(key);pending.push(key);removeFromIndex(key);prepared.queueContexts.set(key,{complete:false,reason:'reconstruction_pending',
      body_position_available:false,record_keys:[],dependency_key:dependency,availability:kind});
  };
  // Bound local ambiguity work per prepared window. Exhausting this display
  // budget withholds the remaining bodies; it never certifies independence.
  const checkBudget=Math.max(4096,rows.size*64);let checks=0,budgetExhausted=false;
  for(let index=0;index<pending.length;index++) {
    if(!remaining.size)break;
    const key=pending[index],record=rows.get(key),domain=domains.get(key),candidates=new Set(unknown);
    if(!record || !domain || domain.unknown)for(const member of remaining)candidates.add(member);
    else {
      if(!eachCell(domain,cell=>{for(const member of cells.get(cell) || [])candidates.add(member);}))for(const member of remaining)candidates.add(member);
      for(const corridor of domain.corridors)for(const member of corridors.get(corridor) || [])candidates.add(member);
    }
    if(record) {
      for(const adjacent of contiguous(record))
        enqueue(keyOf(adjacent),key,'dependent_on_unreconstructed_interval');
    }
    for(const member of candidates) {
      const other=rows.get(member),area=domains.get(member);if(seen.has(member))continue;
      if(++checks>checkBudget) {
        budgetExhausted=true;
        for(const unresolved of [...remaining])enqueue(unresolved,key,'dependency_budget_unresolved');
        break;
      }
      if(record && Math.max(record.timestamps[0],other.timestamps[0])>Math.min(record.timestamps[1],other.timestamps[1]))continue;
      const overlaps=!domain || domain.unknown || area.unknown ||
        [...domain.corridors].some(corridor=>area.corridors.has(corridor)) ||
        domain.minX<=area.maxX && area.minX<=domain.maxX && domain.minY<=area.maxY && area.minY<=domain.maxY;
      if(overlaps)enqueue(member,key,'possible_body_support_dependency');
    }
    if(++count%128===0)await preparationYield(signal);
    if(budgetExhausted)break;
  }
  prepared.partialAvailability={policy:partialVisualPolicy.policy,pending_intervals:seen.size,
    inspected_intervals:rows.size,candidate_checks:checks,check_budget:checkBudget,budget_exhausted:budgetExhausted,
    scope:'loaded_window_and_native_context',certified:false};
}
async function prepareContinuousWindow(payload,prepared,signal) {
  let count=0;
  prepared.queueRosterCache=[];prepared.transitionPoseCache=new Map();
  await preparePartialAvailability(prepared,signal);
  const arrivalRecords=new Map();
  if(arrivalEffects)for(const records of prepared.timelines.values())for(const record of records) {
    const key=JSON.stringify([record.vehicle,record.Trip?.Trip_ID ?? record.Replay_Journey_Key]);
    const old=arrivalRecords.get(key);
    if(!old || record.timestamps[1]>old.timestamps[1])arrivalRecords.set(key,record);
    if(++count%512===0)await preparationYield(signal);
  }
  prepared.arrivalCandidates=[];
  for(const record of arrivalRecords.values()) {
    const catalog=SimZ1VehicleCatalog.resolve(record),end=record.timestamps[1];
    const motion=motionAt(record,end);
    const row=SimZ1ArrivalEffects.candidate(record,{family:catalog.family,width:catalog.dimensions?.width_m ?? 1.8,
      color:motion.available ? visualSpeedColor(motion.speed_kmh) : [160,160,180],horizon:FINAL});
    if(row.reason==='confirmed_native_arrival' && spatialRenderer && !spatialRenderer.contains(row.position))
      row.reason='final_position_outside_loaded_domain';
    prepared.arrivalCandidates.push(row);
    if(++count%128===0)await preparationYield(signal);
  }
  // The live frame keeps its own maps while the successor is prepared in slices.
  // Geometry is shared and immutable; no partial window is ever published.
  for(const record of prepared.holdRecords) {
    const hold=queueHoldTime(record);
    const pose=markerAt(record,hold,null,prepared);
    if(pose) {
      const key=JSON.stringify([record.vehicle,record.Replay_Journey_Key ?? '',record.Link_ID,record.timestamps]);
      const certified=prepared.queueContextMembers.has(key);
      prepared.queueRosterCache.push({...pose,Visual_Queue_Context:prepared.queueContexts.get(key)?.reason==='reconstruction_pending' ?
        prepared.queueContexts.get(key) : certified ?
        {complete:true,member_of_complete_closure:true,role:'resolved_anchor',
          phase:prepared.queueContextPhases.get(key),
          ...(prepared.queueContextCheckpoints.get(key)?{checkpoint:prepared.queueContextCheckpoints.get(key)}:{})} :
        {complete:false,reason:'auxiliary_transition_without_anchor_certificate',role:'auxiliary_transition'}});
    }
    if(++count%128===0)await preparationYield(signal);
  }
  for(const record of activeRecordsAt(payload.start_seconds,prepared.intervalIndex)) {
    const key=markerKey(record),pair=prepared.transitionRecords.get(key) || {};
    const pose=(r,at,inclusive)=>r ? markerAt(r,at,laneObservationAt(r.vehicle,r.Link_ID,at,inclusive,prepared.laneTimelines),prepared) : null;
    prepared.transitionPoseCache.set(key,{
      previous:pose(pair.previous,pair.previous?.timestamps[1],false),next:pose(pair.next,pair.next?.timestamps[0],true)});
    if(++count%128===0)await preparationYield(signal);
  }
}
function replaceContinuousWindow(payload,prepared) {
  // Atomic reference swap: sorting, interval trees and lane/signal preparation
  // already completed before the loader made this window eligible for activation.
  prepared=prepared || SimZ1ContinuousLoader.prepare(payload);
  arrivalWindowCandidates=prepared.arrivalCandidates || [];
  if(arrivalEffects){arrivalEffects.setIdentity(payload);arrivalEffects.ingest(arrivalWindowCandidates);}
  incidentEffects?.replace(prepared.syntheticIncidents,payload);
  timelines=prepared.timelines;recordsByTrip=prepared.recordsByTrip;laneTimelines=prepared.laneTimelines;
  signalTimelines=prepared.signalTimelines;transitionRecords=prepared.transitionRecords;
  transitionTimelines=prepared.transitionTimelines;transitionPoseCache=prepared.transitionPoseCache || new Map();
  queueContexts=prepared.queueContexts || new Map();
  queueRosterCache=prepared.queueRosterCache ?? null;incidents=prepared.incidents;intervalIndex=prepared.intervalIndex;
  firstWindowFrame=performance.now();
  lastMarkerTime=null;lastSignalTime=null;incidentKey=null;hovered=null;selectionChanged=true;
}
function requestContinuousTime(time,seek=false) {
  if(!continuousReplay || !Number.isFinite(time))return;
  time=Math.max(INITIAL,Math.min(FINAL,time));
  if(seek) {
    arrivalEffects?.reset(time,'seek');
    if(continuousReplay.activeIndex===continuousReplay.indexAt(time))arrivalEffects?.ingest(arrivalWindowCandidates);
  } else if(continuousReplay.activeIndex!=null && continuousReplay.indexAt(time)>continuousReplay.activeIndex+1) {
    // A slow RAF must not skip an unobserved window and its arrivals. Advance
    // to the next boundary if the target skips an entire window. Ordinary
    // crossings retain their exact fractional target and native playback speed.
    // This bounds visual catch-up only, never changes native event timestamps.
    time=Math.min(time,continuousReplay.bounds(continuousReplay.activeIndex)[1]);
  }
  // Most frames remain in the already indexed window. They need no cache
  // activation, eviction, notification or transient loading status.
  if(continuousPendingTime==null && continuousReplay.activeIndex===continuousReplay.indexAt(time)) {
    if(seek)continuousReplay.requestTime(time,{seek:true}); // Also cancels a superseded distant demand.
    else continuousReplay.prefetch(continuousReplay.activeIndex);
    current=time;
    arrivalEffects?.advance(current);
    if(time>=FINAL){paused=true;toggle.textContent='Reproducir';}
    if(seek){previous=performance.now();render();}
    return;
  }
  continuousPendingTime=time;continuousError=null;
  continuousWaitStart=performance.now();
  const ready=continuousReplay.requestTime(time,{seek});
  if(ready) {
    current=time;continuousPendingTime=null;
    arrivalEffects?.advance(current);
    if(time>=FINAL){paused=true;toggle.textContent='Reproducir';}
    recordWindowTransition(time,true);
  }
  if(seek)previous=performance.now();
  updateContinuousStatus();
  if(seek)render();
}
function recordWindowTransition(time,ready) {
  continuousPerformance.transitions.push({time,index:continuousReplay.indexAt(time),speed,readyBeforeDemand:ready,
    waitMs:continuousWaitStart==null ? 0 : performance.now()-continuousWaitStart});
  if(continuousPerformance.transitions.length>32)continuousPerformance.transitions.shift();continuousWaitStart=null;
}
let continuousStatus=null,continuousRetry=null,continuousError=null;
function updateContinuousStatus() {
  if(!continuousStatus)return;
  const waitingSeconds=continuousWaitStart==null ? 0 : Math.max(0,Math.floor((performance.now()-continuousWaitStart)/1000));
  const busy=continuousState?.retryingIndices?.includes(continuousReplay?.wantedIndex);
  const statusText=continuousError ? continuousError : continuousPendingTime!=null ?
    'Cargando '+(config.temporal_policy ? formatClock(continuousPendingTime) : formatDuration(continuousPendingTime))+
    ' ('+waitingSeconds+' s)'+(busy ? '; servidor ocupado, reintento automatico' : '; preparando ventana')+(continuousReplay?.activeIndex==null ? '; sin fotograma validado' :
      '; se conserva el fotograma de '+(config.temporal_policy ? formatClock(current) : formatDuration(current))) :
    current>=FINAL ? 'Fin de observación: no existe continuación registrada. Los censurados no son llegadas.' :
    'Reproducción continua';
  if(continuousStatus.textContent!==statusText)continuousStatus.textContent=statusText;
  continuousRetry.hidden=!continuousError;
  if(continuousPendingTime!=null)seeker.value=continuousPendingTime;
}
if(continuousMode) {
  continuousStatus=document.createElement('div');continuousStatus.id='simz1-continuous-status';
  continuousStatus.setAttribute('role','status');continuousStatus.style.gridColumn='1/-1';
  continuousRetry=document.createElement('button');continuousRetry.textContent='Reintentar carga';continuousRetry.hidden=true;
  continuousRetry.onclick=()=>{
    const time=continuousPendingTime ?? current;continuousError=null;
    continuousWaitStart=performance.now();
    if(continuousReplay.retry(time)){current=time;continuousPendingTime=null;arrivalEffects?.advance(current);render();}
    updateContinuousStatus();
  };
  hud.append(continuousStatus,continuousRetry);
  continuousReplay=new SimZ1ContinuousLoader({...config.continuous,...config.continuous.playback,visible_end_seconds:FINAL,prefetch_after_ready:true},{
    canPrefetch:()=>!paused,
    validatePayload:validateSpatialPayload,
    preparePayload:prepareContinuousWindow,
    onWindow:replaceContinuousWindow,
    onState:state=>{continuousState=state;updateContinuousStatus();},
    onReady:index=>{
      if(continuousPendingTime==null || continuousReplay.indexAt(continuousPendingTime)!==index)return;
      current=continuousPendingTime;continuousPendingTime=null;continuousError=null;previous=performance.now();
      arrivalEffects?.advance(current);
      recordWindowTransition(current,false);
      if(current>=FINAL){paused=true;toggle.textContent='Reproducir';}
      render();updateContinuousStatus();
    },
    onError:(index,error)=>{
      if(continuousPendingTime!=null && continuousReplay.indexAt(continuousPendingTime)===index) {
        reportViewerError(error,'ventana '+index);
        continuousError=error.message+'. El reloj permanece en '+(config.temporal_policy ? formatClock(current) : formatDuration(current))+'.';
        // Validation happens before activation. Preserve the last validated
        // frame and selection; a failed request is not evidence of empty roads.
      }
      updateContinuousStatus();
    }
  });
  window.simz1Continuous={
    seek:time=>requestContinuousTime(Math.max(INITIAL,Math.min(FINAL,Number(time))),true),
    setSpeed:value=>{if(value!==1 && value!==120)throw new Error('Velocidad admitida: 1x o 120x');setSpeed(value);},
    setClockFormat,
    play:()=>{previous=performance.now();paused=(continuousPendingTime ?? current)>=FINAL;toggle.textContent=paused ? 'Reproducir' : 'Pausar';render();},
    pause:()=>{advance(performance.now());paused=true;toggle.textContent='Reproducir';render();},
    retry:()=>continuousRetry.onclick(),
    retryJourney:()=>journeyRetry.onclick(),
    reloadHud:()=>loadRunHud(),
    getPerformance:()=>({...diagnosticProvenance(),selectionRequests:{...selectionRequests,samples:selectionRequests.samples.slice(),
        retainedJourneys:fullJourneyRecords ? 1 : 0,retainedJourneySegments:fullJourneyRecords?.length ?? 0},
      ...continuousPerformance,loader:continuousReplay.snapshot(),heap:performance.memory ? {
        usedJSHeapSize:performance.memory.usedJSHeapSize,totalJSHeapSize:performance.memory.totalJSHeapSize} : null}),
    getRenderPerformance:()=>({run_id:config.continuous.run_id,drawRateLimit:maxDrawHz,clockTime:current,displayedTime:lastRenderedTime,
      features:{activePublicVehicles:activePublicVehicleCount,
        work:{...featureWork},
        signals:typeof signalGeometry!=='undefined' ? signalGeometry.records.length : null,
        stops:typeof transitStops!=='undefined' ? transitStops.records.length : null,
        staticBuild:typeof staticFeaturePerformance!=='undefined' ? {...staticFeaturePerformance} : null},
      counters:{...renderCounters},frames:continuousPerformance.frames.slice(),lastDeckDrawCpuMs,
      note:'Stage times and Deck callbacks measure CPU; GPU execution, total allocations and GC require DevTools. Marker counters are partial allocations.'}),
    resetRenderMetrics:()=>{continuousPerformance.frames.length=0;for(const key of Object.keys(renderCounters))renderCounters[key]=0;
      for(const key of Object.keys(featureWork))featureWork[key]=0;},
    setRenderRate:value=>{if(!Number.isFinite(value) || value<15 || value>120)throw new Error('Frecuencia de dibujo: 15..120 Hz');maxDrawHz=value;},
    setQueueGap,
    setSafetyEnvelope,
    getVehicleCatalog:()=>({version:SimZ1VehicleCatalog.version,assumed_dimensions:SimZ1VehicleCatalog.assumptions,
      dimension_precedence:['Vehicle_Dimensions','Vehicle_Physical_Dimensions','family_assumption'],
      spacing:{units:'meters',gap_m:visualQueueRenderer?.settings.gap_m ?? null,
        lateral_clearance_per_side_m:visualQueueRenderer?.settings.lateral_clearance_m ?? null,
        center_distance_formula:'(leader_length_m + follower_length_m) / 2 + gap_m'},
      picking:{units:'css_pixels_from_body_edge',mouse:SimZ1VehiclePicking.radius('mouse'),touch:SimZ1VehiclePicking.radius('touch')},
      note:'Dimensiones registradas con procedencia cuando existen; supuestos por familia en otro caso. VehicleType configurado no implica medición. PCU, cuerpo, envolvente y selección son independientes.'}),
    getVisualDiagnostics,
    getIncidentDiagnostics:()=>({...diagnosticProvenance(),...incidentEffects?.snapshot(current)}),
    getStopDiagnostics:()=>({...diagnosticProvenance(),
      ...(typeof transitStops!=='undefined' ? transitStops.snapshot() : {status:'stop_catalog_unavailable'})}),
    getArrivalDiagnostics:()=>({...diagnosticProvenance(),...arrivalEffects?.snapshot(),
      note:'Anotaciones de llegada; no son vehiculos activos ni predicciones. Sin fin de servicio nativo no se anuncia llegada de buses.'}),
    getTransitDiagnostics:()=>({...diagnosticProvenance(),public_transport:runHudState.data?.public_transport ?? null,
      publicVehiclesWithActiveReplayInterval:activePublicVehicleCount,arrivalAnnotationsExcluded:true,
      selected:pinned?.Trip?.Transit ? {identity:pinned.Trip.Transit,state:SimZ1ContinuousLoader.transitState(pinned,current)} : null,
      note:'Intervals in the loaded replay, not a live QSim counter; terminal gaps do not create active bodies.'}),
    setArrivalStyle:style=>{
      if(!['soft_pulse','steady_tint_and_fade'].includes(style))throw new Error('Estilo: soft_pulse o steady_tint_and_fade');
      if(arrivalEffects)arrivalEffects.reducedMotion=style==='steady_tint_and_fade';render();
    },
    getSignalDiagnostics:()=>({
      ...diagnosticProvenance(),time:current,
      ...(typeof signalGeometry!=='undefined' ? signalGeometry.snapshot() : {available:false,reason:'signal_geometry_not_loaded'}),
      states:(typeof signalGeometry!=='undefined' ? signalGeometry.records : []).map(row=>({
        system_id:row.system_id,group_id:row.group_id,signal_id:row.signal_id,Link_ID:row.Link_ID,lane_ids:row.lane_ids,
        state:signalStateAt(row.system_id,row.group_id,current),observation:signalObservationAt(row.system_id,row.group_id,current)})) || []}),
    diagnoseVehicle,
    traceVehicle:(vehicle,times)=>times.map(time=>diagnoseVehicle(vehicle,time)),
    traceSelectedVehicle:(times=[current-.1,current,current+.1])=>({
      ...diagnosticProvenance(),displayed_time:lastRenderedTime,
      vehicle_id:pinned?.vehicle ?? null,
      note:'Only the loaded window and recorded neighbours are inspected; no seek or fetch. Missing times remain window_not_loaded.',
      records:pinned?.vehicle ? times.map(time=>diagnoseVehicle(pinned.vehicle,time)) : []}),
    selectActive:(index=0)=>{const object=layers.find(layer=>layer.id==='trips')?.props.data[index];
      if(!object)return false;inspectClickedObject(object);return true;},
    clearSelection,
    getState:()=>({current,speed,paused,clockFormat,buffering:continuousPendingTime!=null,pendingTime:continuousPendingTime,
      camera:{mode:cameraMode,viewState:{...cameraViewState}},
      error:continuousError,visibilityStatus:continuousPendingTime!=null ? 'waiting_for_window' : 'ready',
      selectedKey:tripKey(pinned),selectedJourneyStatus:selectionJourneyStatus?.state ?? null,
      selectedVehicleId:pinned?.vehicle ?? null,selectedPersonId:pinned?.Agent_ID ?? pinned?.Trip?.Person_ID ?? null,
      vehicleHighlights:vehicleHighlights.map(({marker,mode})=>({mode,vehicleId:marker.vehicle,
        personId:marker.Agent_ID ?? marker.Trip?.Person_ID ?? null,linkId:marker.Link_ID,
        position:marker.position,heading:marker.Visual_Body_Heading_Degrees})),
      vehicleCard:{...vehicleCardState,fields:vehicleCardState.fields ? {...vehicleCardState.fields} : null},
      selectedTripStatus:pinned?.vehicle ? replayTrip(pinned.Trip).Status ?? null : null,
      selectedArrival:pinned?.vehicle ? replayTrip(pinned.Trip).Arrival ?? null : null,
      selectedJourneyError:selectionJourneyStatus?.state==='unavailable' ? selectionJourneyStatus.message : null,
      selectedRecords:selectedHistory.length,selectedStart:selectedHistory[0]?.timestamps[0] ?? null,
      selectedEnd:selectedHistory[selectedHistory.length-1]?.timestamps[1] ?? null,
      activeAgents:activeAgentCount,activePublicVehicles:activePublicVehicleCount,visibleMarkers:visibleMarkerCount,hud:runHudState,
      spatial:{available:Boolean(spatialRenderer),scope:spatialRenderer ? 'observed_z1_only' : null,
        selectedOD:spatialRenderer && pinned?.vehicle ? pinned.Trip?.OD ?? null : null},
      picking:{mouseRadiusPixels:8,touchRadiusPixels:18},
      visualQueues:{available:Boolean(visualQueueRenderer),gap_m:queueGapMeters,motionUnavailable:motionUnavailableCount,...visualQueueCounts},
      visualLanes:{available:Boolean(config.visual_lanes?.available),links:Object.keys(config.visual_lanes?.links || {}).length,
        renderedLanes:layers.find(layer=>layer.id==='visual-lane-centers')?.props.data.length ?? 0,
        geometry:visualLaneRenderer?.snapshot?.(),...visualLaneCounts},
      loadedVehicles:timelines.size,cache:continuousReplay.snapshot(),
      run_id:config.hud.run_id,iteration:config.hud.iteration,source_version:config.continuous.source_version,
      replay_source:config.replay_source}),
    get deck(){return deckInstance;},
    get layers(){return layers;}
  };
  runHud=new SimZ1ContinuousHud(config.continuous,{onState:updateRunHud});
  loadRunHud();
  requestContinuousTime(INITIAL,true);
}
document.addEventListener('visibilitychange', () => {
  previous = null;
  // RAF may be suspended in a hidden tab. Remove expired annotations on return
  // without advancing the replay or replaying arrivals from the hidden period.
  if(continuousMode && !document.hidden && (arrivalEffects?.needsFrame() || arrivalAnnotationsDrawn))render();
});
requestAnimationFrame(animate); render();
