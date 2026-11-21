const fs=require('fs'),vm=require('vm'),assert=require('assert');
const sourceDirectory=process.env.SIMZ1_RENDER_SOURCE_DIR || 'python';
const controlsSource=fs.readFileSync(require('node:path').join(sourceDirectory,'visualizador_z1_controls.js'),'utf8');
function loadControls(context) {
  vm.createContext(context);
  // Like the continuous replay harness, provide a browser window per VM.
  // Replace any window inherited by sandbox spread and bind this VM's mocks.
  vm.runInContext('window={location:{href:""},document,performance,requestAnimationFrame};window.window=window;',context);
  vm.runInContext(controlsSource,context);
  assert.strictEqual(context.window.document,context.document);
  assert.strictEqual(context.window.performance,context.performance);
  assert.strictEqual(context.window.requestAnimationFrame,context.requestAnimationFrame);
}
let timestamp=0;
const trip={vehicle:'v',Agent_ID:'p',Link_ID:'l',Trip:{Departure:32390,Arrival:32520,Origin_Node:'n1',Destination_Node:'n2',Origin_Position:[0,0],Destination_Position:[10,20]},Speed_kmh:36,color:[255,210,40],path:[[0,0],[10,20]],timestamps:[32400,32520]};
const layer={id:'trips',props:{data:[trip]},clone(p){return {...this,props:{...this.props,...p}};}};
function element(tag='div') {
 const children=[];
 const node={tagName:tag.toUpperCase(),style:{},children,open:false,
  append(...nodes){children.push(...nodes);},appendChild(child){children.push(child);},
  setAttribute(){},contains(other){return other===node || children.some(child=>child.contains?.(other));}};
 return node;
}
const sandbox={Map,Math,String,performance:{now:()=>timestamp},requestAnimationFrame:()=>{},
 document:{hidden:false,createElement:element,body:element('body'),addEventListener(){}},
 deckInstance:{props:{layers:[layer,{...layer,id:'incidents',props:{data:[{incident:true,Link_ID:'l',start:32430,end:32490,capacity:400,speed:10}]}}]},setProps(p){Object.assign(this.props,p);}}};
sandbox.config={hud:{totalAgents:612866}}; // Stale metadata must never determine the counter.
sandbox.replaySegments=[trip]; sandbox.incidentRecords=sandbox.deckInstance.props.layers[1].props.data; sandbox.layers=sandbox.deckInstance.props.layers;
sandbox.replaySegments.push({...trip,timestamps:[60000,60060],Trip:{...trip.Trip,Departure:60000,Arrival:60060}});
loadControls(sandbox);
const val=s=>vm.runInContext(s,sandbox);
assert.strictEqual(val('diagnosticProvenance().client_build'),null,'missing build metadata remains null');
assert.strictEqual(val('visualFrameDiagnostics.client_build'),null,'initial render retains absent build metadata');
// An opaque test sentinel checks pass-through; it is not a fabricated build version.
const buildSentinel=val('window.simz1ClientBuild=Object.freeze({test_only:"provenance sentinel"})');
assert.strictEqual(val('diagnosticProvenance().client_build'),buildSentinel,'provenance preserves the supplied build object');
assert.strictEqual(val('completeVisualDiagnostics(current,null,[]).client_build'),buildSentinel,
  'complete visual diagnostics preserve the supplied build object');
val('delete window.simz1ClientBuild');
assert.strictEqual(val('completeVisualDiagnostics(current,null,[]).client_build'),null,'absent build is not retained from a prior call');
assert.equal(val('current'),0);
assert.ok(val('clock.textContent').includes('Agentes activos visibles: 0'));
assert.equal(val('totalAgents.textContent'),'Vehiculos: 1');
assert.equal(val('technicalHelp.tagName'),'DETAILS');
assert.equal(val('technicalHelp.open'),false,'technical explanations start collapsed');
assert.equal(val('technicalHelp.contains(technicalHelpContent)'),true);
assert.equal(val('technicalHelp.contains(technicalStats)'),true);
assert.equal(val('technicalStats.textContent'),'Vehiculos reconstruidos: 1','full statistics remain accessible');
assert.equal(val('uiShell.contains(hud) && uiShell.contains(clock) && uiShell.contains(info)'),true);
assert.equal(val('uiShell.id'),'simz1-ui');
assert.equal(val('hud.id'),'simz1-controls');
assert.equal(val('info.id'),'simz1-active-telemetry');
for(const name of ['hud','clock','totalAgents','info']) {
 assert.ok(!/position\s*:\s*fixed/.test(val(`${name}.style.cssText || ''`)),name+' uses shared responsive layout');
}
const legendText=val('legend.innerHTML').replace(/<[^>]*>/g,'').replace(/&gt;/g,'>').replace(/&lt;/g,'<').replace(/&nbsp;/g,' ').replace(/\s+/g,' ').trim();
assert.equal(legendText,'Verde >40 km/h | Amarillo 15–40 km/h | Rojo <15 km/h | Blanco = 0 km/h');
assert.ok(!val('legend.innerHTML').includes('<br>'),'primary legend stays one concise row');
assert.equal(val('realtime.textContent'),'1x');
assert.equal(val('original.textContent'),'120x');
assert.equal(val('realtime.title'),'Tiempo real (1x)');
assert.equal(val('original.title'),'Reproduccion acelerada (120x)');
console.log('PASS: compact legend, initially closed technical help, complete secondary metadata and shared layout');
assert.equal(val('seeker.min'),0);
assert.equal(val('seeker.max'),86400);
for (const [time,label] of [[0,'12:00:00 AM'],[43199,'11:59:59 AM'],[43200,'12:00:00 PM'],[64800,'06:00:00 PM'],[86399,'11:59:59 PM'],[86400,'24:00:00 (dia 2)'],[90061,'25:01:01 (dia 2)']]) {
  assert.equal(val(`formatClock(${time})`),label);
}
val('seeker.value=32400; seeker.oninput()');
val('animate(0); animate(500)');
assert.equal(val('current'),32460);
assert.ok(val('clock.textContent').includes('Agentes activos visibles: 1'));
val('render(); render()');
assert.ok(val('clock.textContent').includes('Agentes activos visibles: 1'));
assert.equal(val('deckInstance.props.layers[0].props.data.length'),1);
assert.equal(val('deckInstance.props.layers[0].props.data[0].position[0]'),5);
assert.equal(val('deckInstance.props.layers[0].props.data[0].position[1]'),10);
assert.equal(val('deckInstance.props.layers[0].props.data[0].color[1]'),210);
timestamp=500;val('toggle.onclick(); animate(5000)');assert.equal(val('current'),32460);
assert.ok(val('clock.textContent').includes('Agentes activos visibles: 1'));
timestamp=5000;val('toggle.onclick(); animate(5500)');
assert.equal(val('deckInstance.props.layers[0].props.data.length'),0);
assert.ok(val('clock.textContent').includes('Agentes activos visibles: 0'));
console.log('PASS: single moving marker, interpolation, color, pause and no residual trail');
timestamp=5500;
val('toggle.onclick(); seeker.value=32430; seeker.oninput()');
assert.equal(val('paused'),true);
assert.equal(val('current'),32430);
assert.equal(val('deckInstance.props.layers[0].props.data[0].position[0]'),2.5);
val('realtime.onclick()');
assert.equal(val('speed'),1);
assert.equal(val('paused'),true);
val('toggle.onclick(); animate(6500)');
assert.equal(val('current'),32431);
timestamp=6500;val('original.onclick(); animate(7000)');
assert.equal(val('current'),32491);
timestamp=7000;val('seeker.value=54000; seeker.oninput()');
assert.equal(val('current'),54000);
assert.ok(val('clock.textContent').startsWith('03:00:00 PM'));
assert.equal(val('deckInstance.props.layers[0].props.data.length'),0);
val('animate(7500)');assert.equal(val('current'),54060);
timestamp=7500;val('seeker.value=86400; seeker.oninput(); animate(8000)');
assert.equal(val('current'),60);
assert.ok(val('clock.textContent').startsWith('12:01:00 AM'));
timestamp=7500;val('seeker.value=32400; seeker.oninput()');
assert.equal(val('deckInstance.props.layers[0].props.data[0].position[0]'),0);
assert.equal(val('lastSignalTime'),val('current'));
assert.equal(val("signalStateAt('missing','avenida',current)"),'UNKNOWN');
assert.ok(val('clock.textContent').startsWith('09:00:00 AM'));
console.log('PASS: seek forward/backward, paused seek, 1x/120x, endpoint, loop and synchronized clock/signals');
val('deckInstance.props.onClick({object:deckInstance.props.layers[0].props.data[0]}); deckInstance.props.onHover({object:null}); render()');
assert.ok(val('info.textContent').includes('Nodo de origen: n1'));
assert.ok(val('info.textContent').includes('Nodo de destino: n2'));
assert.ok(val('info.textContent').includes('maxima hasta aqui: 36.0'));
assert.ok(val('info.textContent').includes('00:00:10'));
assert.equal(val('info.style.display'),'block');
val('seeker.value=32460; seeker.oninput()');
assert.ok(val('info.textContent').includes('00:01:10'));
val('seeker.value=32400; seeker.oninput()');
assert.ok(val('info.textContent').includes('00:00:10'));
val('deckInstance.props.onClick({object:null})');
assert.equal(val('info.style.display'),'none');
console.log('PASS: trip details, elapsed time on seek and persistent click inspection');
val('seeker.value=32429; seeker.oninput()');
assert.equal(val('deckInstance.props.layers[1].props.data.length'),0);
val('seeker.value=32430; seeker.oninput()');
assert.equal(val('deckInstance.props.layers[1].props.data.length'),1);
assert.ok(val('tooltipText(deckInstance.props.layers[1].props.data[0])').includes('400 veh/h'));
val('seeker.value=32490; seeker.oninput()');
assert.equal(val('deckInstance.props.layers[1].props.data.length'),0);
val('seeker.value=32450; seeker.oninput()');
assert.equal(val('deckInstance.props.layers[1].props.data.length'),1);
console.log('PASS: incident boundaries, recovery, reverse seeking and tooltip');

val('seeker.value=32460; seeker.oninput(); deckInstance.props.onClick({object:deckInstance.props.layers[0].props.data[0]})');
assert.equal(val('selectedHistory.length'),1);
assert.equal(val('selectedEndpoints.length'),2);
assert.equal(val('selectedEndpoints[0].kind'),'origin');
assert.deepEqual(Array.from(val('selectedEndpoints[0].position')),[0,0]);
assert.equal(val('selectedEndpoints[1].icon'),'finish');
assert.deepEqual(Array.from(val('selectedEndpoints[1].position')),[10,20]);
assert.equal(val('deckInstance.props.getTooltip'),null);
assert.ok(val('hud.contains(clock)'),'clock remains in the controls layout');
val('deckInstance.props.onClick({object:null})');
assert.equal(val('selectedHistory.length'),0);
assert.equal(val('selectedEndpoints.length'),0);
console.log('PASS: exclusive selection history, OD colors, clearing, clock in controls and no floating tooltip');
const split = val('splitSelectedRoute(selectedHistory,32460)');
// Selection was cleared above: both layers must remain empty.
assert.equal(split.history.length,0); assert.equal(split.future.length,0);
val('selectedHistory = [timelines.get("v")[0]]');
for (const [time,past,future] of [[32389,0,0],[32399,0,1],[32400,0,1],[32460,1,1],[32520,0,0],[32600,0,0]]) {
  const route=val(`splitSelectedRoute(selectedHistory,${time})`);
  assert.equal(route.history.length,past); assert.equal(route.future.length,future);
  if(time===32460) {
    assert.deepEqual(Array.from(route.history[0].path[1]),[5,10]);
    assert.deepEqual(Array.from(route.future[0].path[0]),[5,10]);
  }
}
console.log('PASS: PathLayer split, exact marker position, journey-exclusive arrival and clearing');
val('layers.push({...layers[0],id:"selected-history"},{...layers[0],id:"selected-future"}); seeker.value=32460; seeker.oninput(); deckInstance.props.onClick({object:timelines.get("v")[0]})');
assert.equal(val('layers.find(l=>l.id==="selected-history").props.data.length'),1);
assert.equal(val('layers.find(l=>l.id==="selected-future").props.data.length'),1);
val('seeker.value=32400; seeker.oninput()');
assert.equal(val('layers.find(l=>l.id==="selected-history").props.data.length'),0);
val('deckInstance.props.onClick({object:null})');
assert.equal(val('layers.find(l=>l.id==="selected-future").props.data.length'),0);
console.log('PASS: both route layers update on click, reverse seek and deselection');
val('timelines.get("v")[0].Profile="Liebre"; seeker.value=32460; seeker.oninput()');
assert.ok(val('tooltipText(timelines.get("v")[0])').startsWith('Agente: p | Perfil: Liebre'));
console.log('PASS: driving profile in agent panel');
for (const [time,count] of [[32399,0],[32400,1],[32520,0],[32521,0],[32460,1],[60000,1],[60060,0]]) {
  val(`seeker.value=${time}; seeker.oninput(); render()`);
  assert.ok(val('clock.textContent').includes(`Agentes activos visibles: ${count}`));
  assert.equal(val('totalAgents.textContent'),'Vehiculos: 1');
}
console.log('PASS: unique vehicle keys, inclusive start/exclusive end, reverse seeking and stable total');
val('timelines.get("v")[0].Movement_End=32410; timelines.get("v")[0].Motion_Speed_kmh=36');
for (const [time,x,speed] of [[32400,0,36],[32405,5,36],[32410,10,0],[32519,10,0],[32405,5,36]]) {
  val(`seeker.value=${time}; seeker.oninput()`);
  assert.equal(val('layers[0].props.data[0].position[0]'),x);
  assert.equal(val('layers[0].props.data[0].Visual_Speed_kmh'),speed);
  assert.deepEqual(Array.from(val('layers[0].props.data[0].color')),speed === 0 ? [255,255,255] : [255,210,40]);
  assert.ok(val('clock.textContent').includes('Agentes activos visibles: 1'));
}
val('seeker.value=32520; seeker.oninput()');
assert.equal(val('layers[0].props.data.length'),0);
console.log('PASS: free-flow motion, stationary queue until left link, backward seek and active count');
const smooth = val('markerAt({...timelines.get("v")[0],timestamps:[0,12],Movement_End:12,Motion_Speed_kmh:30},11)');
assert.ok(smooth.position[0] < 10);
assert.equal(smooth.Waiting,false);
assert.notDeepEqual(Array.from(smooth.color),[255,255,255]);
const stopped = val('markerAt({...timelines.get("v")[0],path:[[1,2],[1,2]],timestamps:[0,12],Movement_End:12},6)');
assert.equal(stopped.Visual_Speed_kmh,0);
assert.deepEqual(Array.from(stopped.color),[255,255,255]);

// Two reconstructed vehicles for the same person are one active visible agent.
val("timelines.set('second-vehicle', [{...timelines.get('v')[0], vehicle:'second-vehicle'}]); intervalIndex=buildIntervalIndex([...timelines.values()].flat()); current=32450; lastMarkerTime=null; render()");
assert.equal(val('activeAgentCount'),1);
assert.equal(val("layers.find(l=>l.id==='trips').props.data.length"),2);
console.log('PASS: active persons are distinct from reconstructed vehicles');

const appended = [];
const warningSandbox = {...sandbox,
  config: {selection_warning:'RESULTADOS ANTERIORES: ultimo intento interrumpido'},
  replaySegments:[], incidentRecords:[], layers:[],
  document:{...sandbox.document,body:{appendChild(node){appended.push(node);}}}};
sandbox.window.simz1ClientBuild=buildSentinel;
loadControls(warningSandbox);
assert.notStrictEqual(warningSandbox.window,sandbox.window,'spread fixtures receive independent windows');
assert.strictEqual(vm.runInContext('diagnosticProvenance().client_build',warningSandbox),null,
  'another context cannot inherit the main context build');
vm.runInContext('window.location.href="test-only-location"',warningSandbox);
assert.strictEqual(sandbox.window.location.href,'','window location is isolated between contexts');
assert.strictEqual(val('diagnosticProvenance().client_build'),buildSentinel,'loading another context preserves the original build');
delete sandbox.window.simz1ClientBuild;
const containsWarning=node=>node.textContent === warningSandbox.config.selection_warning || (node.children || []).some(containsWarning);
assert.ok(appended.some(containsWarning));
console.log('PASS: previous-result warning appears visibly in the HTML controls');

// Lane events locate a vehicle in a QSim queue, never at a measured XY position.
val(`laneTimelines.set('v', [
  {type:'left lane',time:32400,vehicle:'v',link:'l',lane:'l.original',entry_observed:false},
  {type:'entered lane',time:32405,vehicle:'v',link:'l',lane:'l.original'},
  {type:'left lane',time:32410,vehicle:'v',link:'l',lane:'l.original',entry_observed:true},
  {type:'entered lane',time:32410,vehicle:'v',link:'l',lane:'l.lane.1'},
  {type:'left lane',time:32420,vehicle:'v',link:'l',lane:'l.lane.1',entry_observed:true},
  {type:'entered lane',time:32430,vehicle:'v',link:'other',lane:'other.original'},
  {type:'vehicle leaves traffic',time:32440,vehicle:'v'}
])`);
for (const [time,lane] of [[32399,null],[32400,null],[32404,null],[32405,'l.original'],
  [32410,'l.lane.1'],[32419,'l.lane.1'],[32420,null],[32435,null],[32445,null],[32406,'l.original']]) {
  assert.equal(val(`laneObservationAt('v','l',${time}).lane`),lane);
  assert.equal(val(`markerAt(timelines.get('v')[0],${time}).Observed_Queue_ID`),lane);
}
val('seeker.value=32400; seeker.oninput()');
assert.ok(val("tooltipText(timelines.get('v')[0])").includes('sin entrada registrada'));
val('seeker.value=32411; seeker.oninput()');
assert.ok(val("tooltipText(timelines.get('v')[0])").includes('Cola/carril registrado: l.lane.1'));
assert.ok(val("tooltipText(timelines.get('v')[0])").includes('interpolada sobre el eje; carril visual no disponible'));
const markerWithLane = val("markerAt(timelines.get('v')[0],32411)");
val("laneTimelines.delete('v')");
const markerWithoutLane = val("markerAt(timelines.get('v')[0],32411)");
assert.deepEqual(Array.from(markerWithLane.position),Array.from(markerWithoutLane.position));
assert.equal(markerWithoutLane.Observed_Queue_ID,null);
assert.ok(val('technicalHelpContent.innerHTML').includes('sin cambio lateral ni car-following continuo'));
assert.ok(val('technicalHelpContent.innerHTML').includes('Sin eventos de carril disponibles'));
console.log('PASS: observed queue membership, partial initial event, stable simultaneous order, reverse seek, traffic boundary and no invented lane offsets');

const midnightTrip={...trip,timestamps:[86399,86500],Trip:{...trip.Trip,Departure:86399,Arrival:86500,Trip_ID:'p:trip:0002'}};
const temporalSandbox={...sandbox,config:{demand_window:{start_seconds:0,end_seconds:86400},
  time_horizon:{start_seconds:0,end_seconds:90000},replay_window:{start_seconds:82800,end_seconds:91000}},
  replaySegments:[midnightTrip],incidentRecords:[],layers:[layer],
  deckInstance:{...sandbox.deckInstance,props:{layers:[layer]}}};
loadControls(temporalSandbox);
const temporalVal=s=>vm.runInContext(s,temporalSandbox);
assert.equal(temporalVal('seeker.min'),82800);
assert.equal(temporalVal('seeker.max'),91000);
temporalVal('seeker.value=86410; seeker.oninput()');
assert.equal(temporalVal('current'),86410);
assert.ok(temporalVal('clock.textContent').startsWith('24:00:10 (dia 2)'));
assert.equal(temporalVal('activeAgentCount'),1);
assert.ok(temporalVal('tooltipText(replaySegments[0])').includes('p:trip:0002'));
assert.ok(temporalVal('technicalHelpContent.innerHTML').includes('El deslizador no genera viajes'));
console.log('PASS: independent demand/simulation/replay windows, trip ID and absolute midnight clock');

// Independent system/group timelines: exact boundaries, reverse seeks and no clock synthesis.
// Production swaps the prepared map atomically; do the same in this fixture so
// the optimized signal-band cache cannot refer to a mutated source map.
val(`signalTimelines=new Map([
     [JSON.stringify(['A','same']), [[10,'GREEN'],[43,'YELLOW'],[47,'RED'],[80,'GREEN']]],
     [JSON.stringify(['B','same']), [[10,'YELLOW'],[10,'RED'],[49,'GREEN'],[74,'YELLOW']]]]);`);
for (const [time,a,b] of [[9,'UNKNOWN','UNKNOWN'],[10,'GREEN','RED'],[43,'YELLOW','RED'],[47,'RED','RED'],
                         [49,'RED','GREEN'],[74,'RED','YELLOW'],[80,'GREEN','YELLOW'],[43,'YELLOW','RED'],[10,'GREEN','RED']]) {
  val(`seeker.value=${time}; seeker.oninput(); render();`);
  assert.equal(val(`signalStateAt('A','same',current)`),a);
  assert.equal(val(`signalStateAt('B','same',current)`),b);
}
assert.equal(val("signalIcon({system_id:'B',group_id:'missing'},100)"),'unknown');
assert.equal(val("signalStateAt('A','same',86480)"),'GREEN'); // Last observation held; no invented cycles.
assert.ok(val("tooltipText({system_id:'A',group_id:'same',Link_ID:'l',lane_ids:['q']})").includes('Estado nativo: GREEN'));
assert.ok(!controlsSource.includes('signalPhase('));
console.log('PASS: native signals by system/group, exact boundaries, initialization order, reverse/paused seek and unknown missing state');
val(`layers.push({id:'signals',props:{data:[{system_id:'A',group_id:'same'},{system_id:'B',group_id:'same'}]},
 clone(props){return {...this,props:{...this.props,...props}};}}); lastSignalTime=null;`);
for (const [time,a,b] of [[10,'green','red'],[49,'red','green'],[43,'yellow','red'],[9,'unknown','unknown']]) {
  val(`seeker.value=${time}; seeker.oninput();`);
  assert.equal(val("layers.find(l=>l.id==='signals').props.getIcon({system_id:'A',group_id:'same'})"),a);
  assert.equal(val("layers.find(l=>l.id==='signals').props.getIcon({system_id:'B',group_id:'same'})"),b);
}
console.log('PASS: rendered icons refresh independently across forward and reverse seeks');

for (const enabled of [true,false]) {
  const prioritySandbox={...sandbox,config:{hud:{priority:{enabled,stop_seconds:5,
    classification:'osm-name-orientation',conflicts:'conservative'}}},replaySegments:[],incidentRecords:[],
    layers:[layer],deckInstance:{...sandbox.deckInstance,props:{layers:[layer]}}};
  loadControls(prioritySandbox);
  const text=vm.runInContext('technicalStats.textContent',prioritySandbox);
  assert.ok(text.includes('Prioridad sin semaforo: '+(enabled?'activada':'desactivada')));
  assert.ok(text.includes('Parada en cabecera: 5 s'));
  assert.ok(text.includes('Clasificacion: osm-name-orientation | Conflictos: conservative'));
  assert.ok(!vm.runInContext('totalAgents.textContent',prioritySandbox).includes('Prioridad sin semaforo'));
}
console.log('PASS: effective priority enable/disable, stop duration and classification/conflict policy accessible in secondary metadata');

const runMetadata={run_id:'run-simz1-12345678-abcdef01',iteration:2,planned_persons:100,
  planned_trips:240,observed_departures:239,demand_seed:17,matsim_seed:23};
const runSandbox={...sandbox,config:{hud:runMetadata,
  lane_replay:{use_lanes:true,event_count:42,vehicles_with_events:1},
  trajectory_stats:{observed_persons:100,vehicles_without_drawable_segments:3,unsampled_vehicles:7}},
  replaySegments:[trip],incidentRecords:[],layers:[layer],
  deckInstance:{...sandbox.deckInstance,props:{layers:[layer]}}};
loadControls(runSandbox);
const runVal=s=>vm.runInContext(s,runSandbox);
assert.equal(runVal('totalAgents.textContent'),'Vehiculos: 1');
assert.ok(!runVal('totalAgents.title'),'identity belongs in Help, not the normal counter');
for(const text of ['Vehiculos reconstruidos: 1','Personas planificadas: 100 | Viajes planificados: 240',
  'Salidas registradas (etapas): 239','Corrida: '+runMetadata.run_id,
  'Semilla demanda: 17 | MATSim: 23 | Iteracion: 2','Carriles configurados: activados',
  'Eventos de cola registrados (muestra): 42 | Vehiculos con eventos: 1',
  'Personas en eventos: 100 | Vehiculos sin intervalo cerrado de duracion positiva: 3 | Excluidos por muestreo: 7']) {
  assert.ok(runVal('technicalStats.textContent').includes(text),text+' retained in secondary metadata');
}
assert.equal(runVal('technicalHelp.open'),false);
assert.ok(runVal('technicalHelpContent.innerHTML').includes('ID de cola y tiempos registrados'));
console.log('PASS: run identity, iteration, seeds, lanes and trajectory counts retained in closed help');

// Prompt 7: limits were resolved during export; the UI preserves measured speed.
const turtle={...trip,vehicle:'turtle',Agent_ID:'turtle-person',timestamps:[86390,86570],
  Movement_End:86570,Motion_Speed_kmh:20,Speed_kmh:20,path:[[0,0],[1000,0]],Profile:'Tortuga'};
sandbox.turtle=turtle;
for(const time of [86462,86569,86400,86390,86500]){
  const marker=val(`markerAt(turtle,${time})`);
  assert.equal(marker.Waiting,false);
  assert.equal(marker.Visual_Speed_kmh,20);
  assert.equal(marker.Speed_kmh,20);
  assert.ok(Math.abs(marker.position[0]-1000*(time-86390)/180)<1e-9);
}
sandbox.signalWait={...turtle,timestamps:[0,210],Movement_End:181,Speed_kmh:1000/210*3.6,
  Motion_Speed_kmh:1000/181*3.6,Wait_Evidence:'native_wait_observation',
  Observed_Waits:{signal_red:{first:181,last:209,attempts:29}}};
for(const [time,waiting] of [[180,false],[181,true],[209,true],[90,false]]){
  const marker=val(`markerAt(signalWait,${time})`);
  assert.equal(marker.Waiting,waiting);
  assert.equal(marker.Speed_kmh,sandbox.signalWait.Speed_kmh);
  if(waiting){assert.equal(marker.Visual_Speed_kmh,0);assert.deepEqual(Array.from(marker.color),[255,255,255]);}
}
console.log('PASS: Turtle no false wait, native signal wait, separate measured/visual speed, midnight and reverse seek');

// Deterministic overlap/index oracle, including zero durations and exact bounds.
sandbox.indexFixtures=Array.from({length:1000},(_,i)=>({vehicle:'index-'+i,timestamps:[i%107,i%107+i%23]}));
val('const testIndex=buildIntervalIndex(indexFixtures)');
for(const time of [0,1,22,107,140,106,105.5,80,20,0,-1]){
  const actual=Array.from(val(`activeRecordsAt(${time},testIndex).map(r=>r.vehicle)`)).sort();
  const expected=sandbox.indexFixtures.filter(r=>r.timestamps[0]<=time&&time<r.timestamps[1]).map(r=>r.vehicle).sort();
  assert.deepEqual(actual,expected);
}
console.log('PASS: interval index equals exhaustive query, overlaps, null intervals, exact limits and inverse time');
val(`timelines.set('unknown-speed', [{...turtle,vehicle:'unknown-speed',timestamps:[0,100],Movement_End:100,
  Trip:{...turtle.Trip,Departure:0,Arrival:100},
  Speed_kmh:null,Max_Speed_kmh:null,Motion_Speed_kmh:10,Inferred:true}]);current=50;`);
assert.ok(val("tooltipText(timelines.get('unknown-speed')[0])").includes('Velocidad media medida del tramo: no disponible'));
assert.ok(val("tooltipText(timelines.get('unknown-speed')[0])").includes('Velocidad maxima hasta aqui: no disponible'));
assert.equal(val("markerAt(timelines.get('unknown-speed')[0],50).Waiting"),false);
console.log('PASS: absent measured speed is unknown, distinct from estimated visual speed and observed zero');
