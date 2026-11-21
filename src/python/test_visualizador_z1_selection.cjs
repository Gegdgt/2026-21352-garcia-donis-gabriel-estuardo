// Prompt 9: the selected journey's lifetime governs every selection layer.
// No WebGL is needed here: clone/setProps capture exactly the submitted data.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('python/visualizador_z1_controls.js', 'utf8');
const selectedLayers = ['selected-history','selected-future','selected-origin','selected-destination'];

function harness(records, configuration={}) {
  let timestamp=0;
  const listeners=new Map(), elements=[];
  function element(tag='div') {
    const children=[];
    const node={tagName:tag.toUpperCase(),style:{},children,open:false,
      append(...nodes){children.push(...nodes);}, appendChild(node){children.push(node);},
      setAttribute(){}, contains(other){return other===node || children.some(child=>child.contains?.(other));},
      closest(){return null;}, addEventListener(type,callback){node['on'+type]=callback;}};
    elements.push(node);
    return node;
  }
  const canvas=element('canvas'), map=element('div'); map.append(canvas);
  const body=element('body'); body.append(map);
  const layer=id=>({id,props:{data:[]},clone(props){return {...this,props:{...this.props,...props}};}});
  const layers=['trips',...selectedLayers].map(layer);
  const document={hidden:false,body,createElement:element,
    addEventListener(type,callback){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(callback);},
    getElementById(id){return ['deck-container','map','map-container'].includes(id)?map:null;},
    querySelector(selector){return selector==='canvas'?canvas:map;}};
  const sandbox={Map,Math,String,Set,console,performance:{now:()=>timestamp},requestAnimationFrame(){},
    window:{},document,config:configuration,replaySegments:records,incidentRecords:[],layers,
    deckInstance:{props:{layers},getCanvas(){return canvas;},setProps(props){Object.assign(this.props,props);}}};
  vm.createContext(sandbox); vm.runInContext(source,sandbox);
  const evaluate=code=>vm.runInContext(code,sandbox);
  return {sandbox,evaluate,listeners,map,canvas,element,
    clock(value){timestamp=value;},
    seek(time){evaluate(`seeker.value=${time};seeker.oninput();`);},
    click(record){sandbox.clicked=record;evaluate('deckInstance.props.onClick({object:clicked});');},
    hover(record){sandbox.hoveredRecord=record;evaluate('deckInstance.props.onHover({object:hoveredRecord});');},
    dispatch(type,event){for(const callback of listeners.get(type)||[])callback(event);},
    counts(){return selectedLayers.map(id=>evaluate(`layers.find(layer=>layer.id===${JSON.stringify(id)}).props.data.length`));},
    panel(){return evaluate('info.style.display');},
    text(){return evaluate('info.textContent');},
    markers(){return evaluate("layers.find(layer=>layer.id==='trips').props.data.length");}};
}

function segment(vehicle,person,trip,start,end,from=0,to=10) {
  return {vehicle,Agent_ID:person,Link_ID:vehicle+'-link-'+start,Trip:trip,
    Profile:'Normal',Speed_kmh:36,Motion_Speed_kmh:36,Movement_End:end,color:[255,210,40],
    path:[[from,0],[to,0]],timestamps:[start,end]};
}
function trip(id,departure,arrival,extra={}) {
  return {Trip_ID:id,Departure:departure,Arrival:arrival,Status:arrival==null?'censored':'completed',
    Last_Observed_Time:arrival,Origin_Node:id+'-origin',Destination_Node:arrival==null?null:id+'-destination',
    Origin_Position:[0,0],Destination_Position:arrival==null?null:[20,0],...extra};
}
function hidden(h,label) {
  assert.deepEqual(h.counts(),[0,0,0,0],label+': all four selection layers must be empty');
  assert.equal(h.panel(),'none',label+': active panel must be hidden');
  assert.equal(h.text(),'',label+': stale active telemetry must be cleared');
}
function visible(h,expected,label) {
  assert.deepEqual(h.counts(),expected,label+': submitted selection layer data');
  assert.equal(h.panel(),'block',label+': journey panel must be visible');
}

const first=trip('person:trip:0001',32390,32520);
const second=trip('person:trip:0002',60000,60060);
const records=[segment('vehicle','person',first,32400,32440,0,10),
  segment('vehicle','person',first,32480,32520,10,20),
  segment('vehicle','person',second,60000,60060,0,20)];
const h=harness(records);
h.seek(32420);h.click(records[0]);visible(h,[1,2,1,1],'initial selection');
assert.ok(h.text().includes(first.Trip_ID));

for(const time of [32520,32521,59000,32389]){
  h.seek(time); hidden(h,'outside first journey at '+time);
  h.evaluate('render(); render();'); hidden(h,'repeated render at '+time);
}
h.seek(32390);visible(h,[0,2,1,1],'departure precedes first reconstructed segment');
assert.equal(h.markers(),0);
assert.ok(h.text().includes('Sin tramo medido activo'));
assert.ok(!h.text().includes('Velocidad visual estimada'));
h.seek(32460);visible(h,[1,1,1,1],'intermediate event gap is not arrival');
assert.equal(h.markers(),0);
assert.ok(h.text().includes('Sin tramo medido activo'));
assert.ok(!h.text().includes('Enlace actual:'));
assert.ok(!h.text().includes('Velocidad visual estimada'));
h.seek(32490);visible(h,[2,1,1,1],'reverse seek restores selected journey');
assert.equal(h.markers(),1);
assert.ok(h.text().includes('Enlace actual:'));
console.log('PASS: exact/exclusive arrival 32520, later 32521, before departure, event gap, reverse seek; four layers and panel');

// Person/vehicle identity alone must never transfer the pinned first trip to a later trip.
h.seek(60020);hidden(h,'later trip of the same person');assert.equal(h.markers(),1);
h.click(records[2]);visible(h,[1,1,1,1],'explicit second-trip selection');
assert.ok(h.text().includes(second.Trip_ID));assert.ok(!h.text().includes(first.Trip_ID));
h.seek(32420);hidden(h,'second trip selected while first trip is active');
h.seek(60020);visible(h,[1,1,1,1],'seek restores second trip');
h.seek(60060);hidden(h,'second trip exact arrival');
h.seek(32420);h.click(records[0]);h.seek(32460);visible(h,[1,1,1,1],'first trip selected again');
console.log('PASS: two trips for one person, inter-trip interval, no automatic transfer, explicit selection and restoration');

// Fast playback may step directly across the boundary without ever rendering the arrival instant.
h.clock(0);h.seek(32400);h.click(records[0]);h.evaluate('animate(1001)');
assert.ok(h.evaluate('current')>32520);hidden(h,'120x crosses arrival');
h.clock(1001);h.seek(32420);visible(h,[1,2,1,1],'seek back after 120x');
h.clock(2000);h.seek(86395);h.evaluate('animate(2100)');
assert.equal(h.evaluate('current'),7);hidden(h,'clock wraps to replay start');
console.log('PASS: 120x skipped boundary and replay clock wrap invalidate all selection data');

// Hover is ephemeral: a stale picked object must not resurrect when time returns.
h.seek(32420);h.click(null);h.hover(records[0]);assert.equal(h.panel(),'block');
h.seek(32521);hidden(h,'stale hover after arrival');
h.seek(32420);hidden(h,'old hover is not restored on reverse seek');
h.hover(records[0]);h.seek(32460);hidden(h,'hover clears in an unobserved intermediate segment gap');
h.hover(null);hidden(h,'pointer leaves map');
h.seek(32420);h.click(records[0]);h.hover(records[0]);h.click(null);hidden(h,'empty map click clears pin and hover');
h.seek(32490);hidden(h,'cleared pin is not restored');
console.log('PASS: stale hover, leave-map hover and empty-map click clear panel and geometry');

// A real DOM click beyond the map must also clear a pin. HUD controls may remain interactive.
h.seek(32420);h.click(records[0]);
const outside=h.element('div');
const registered=['pointerdown','click','mousedown'].filter(type=>h.listeners.has(type));
assert.ok(registered.length,'outside-map clearing must register a document pointer/click listener');
for(const type of registered)h.dispatch(type,{target:h.canvas,composedPath:()=>[h.canvas,h.map,h.sandbox.document.body],button:0});
visible(h,[1,2,1,1],'pointer inside map preserves selection');
const slider=h.evaluate('seeker'), hud=h.evaluate('hud');
for(const type of registered)h.dispatch(type,{target:slider,composedPath:()=>[slider,hud,h.sandbox.document.body],button:0});
visible(h,[1,2,1,1],'HUD interaction preserves selection');
const help=h.evaluate('technicalHelp'), helpContent=h.evaluate('technicalHelpContent');
assert.equal(help.open,false,'technical help initially collapsed');
help.open=true;
for(const type of registered)h.dispatch(type,{target:helpContent,composedPath:()=>[helpContent,help,hud,h.sandbox.document.body],button:0});
visible(h,[1,2,1,1],'opening and interacting with technical help preserves selection');
help.open=false;
for(const type of registered)h.dispatch(type,{target:outside,composedPath:()=>[outside,h.sandbox.document.body],button:0});
hidden(h,'DOM click outside map');
console.log('PASS: click outside the map clears all four layers and active panel');

const censored=trip('censored:trip:0001',10,null,{Last_Observed_Time:80});
const incompleteSegments=[segment('censored-vehicle','censored-person',censored,10,40),
  segment('censored-vehicle','censored-person',censored,60,70,10,20)];
const c=harness(incompleteSegments,{time_horizon:{start_seconds:0,end_seconds:100}});
c.seek(20);c.click(incompleteSegments[0]);visible(c,[1,2,1,0],'censored journey');
c.seek(80);visible(c,[2,0,1,0],'censored last measured instant inclusive');
assert.equal(c.markers(),0);assert.ok(c.text().includes('Sin tramo medido activo'));
c.seek(80.001);hidden(c,'after censored last observation');
c.seek(65);visible(c,[2,1,1,0],'censored reverse seek');
const legacy=trip('legacy:trip:0001',10,null);delete legacy.Last_Observed_Time;delete legacy.Trip_ID;
const legacyRecord=segment('legacy-vehicle','legacy-person',legacy,10,30);
const fallback=harness([legacyRecord]);fallback.seek(20);fallback.click(legacyRecord);
fallback.seek(30);visible(fallback,[1,0,1,0],'legacy last segment end inclusive');
fallback.seek(31);hidden(fallback,'legacy no extrapolation after last measured segment');
const atHorizon=trip('cutoff:trip:0001',10,null,{Abort:140,Last_Observed_Time:140,Observation_End:100,
  Observation_End_Provenance:'configured_horizon'});
const cutoffRecord=segment('cutoff-vehicle','cutoff-person',atHorizon,10,100);
const cutoff=harness([cutoffRecord]);cutoff.seek(99);cutoff.click(cutoffRecord);
visible(cutoff,[1,1,1,0],'before observation horizon');
cutoff.seek(100);hidden(cutoff,'observation horizon is exclusive even with last observation at cutoff');
cutoff.seek(139);hidden(cutoff,'QSim cleanup abort after horizon never extends censored visibility');
console.log('PASS: censored last observation, no extrapolation or invented destination, legacy bounded fallback');

// A stream's final event does not establish an exclusive simulation horizon.
const streamEnd=trip('stream:trip:0001',10,null,{Last_Observed_Time:80,Observation_End:80,
  Observation_End_Provenance:'last_event_in_stream'});
const streamRecord=segment('stream-vehicle','stream-person',streamEnd,10,80);
const stream=harness([streamRecord]);stream.seek(20);stream.click(streamRecord);
stream.seek(80);visible(stream,[1,0,1,0],'last event remains inclusive without a known horizon');
assert.equal(stream.markers(),0);assert.ok(stream.text().includes('Sin tramo medido activo'));
stream.seek(80.001);hidden(stream,'no visibility after final individual stream observation');
stream.seek(60);visible(stream,[1,1,1,0],'reverse seek from final stream observation');
console.log('PASS: stream ending is not a known horizon; last individual observation remains inclusive');

const aborted=trip('abort:trip:0001',100,null,{Status:'aborted',Abort:140,Last_Observed_Time:140});
const abortRecord=segment('abort-vehicle','abort-person',aborted,100,140);
const a=harness([abortRecord]);a.seek(120);a.click(abortRecord);visible(a,[1,1,1,0],'before abort');
a.seek(140);hidden(a,'abort is exclusive');a.seek(141);hidden(a,'after abort');
a.seek(120);visible(a,[1,1,1,0],'reverse seek before abort');
console.log('PASS: abort boundary is exclusive and reverse seek restores only the original journey');

const noIdFirst=trip(null,10,20), noIdSecond=trip(null,30,40);
delete noIdFirst.Trip_ID;delete noIdSecond.Trip_ID;
const noIds=[segment('legacy-shared-vehicle','legacy-shared-person',noIdFirst,10,20),
  segment('legacy-shared-vehicle','legacy-shared-person',noIdSecond,30,40)];
const byDeparture=harness(noIds);byDeparture.seek(15);byDeparture.click(noIds[0]);
visible(byDeparture,[1,1,1,1],'legacy selected trip without Trip_ID');
byDeparture.seek(35);hidden(byDeparture,'legacy Departure distinguishes next trip');
byDeparture.seek(15);visible(byDeparture,[1,1,1,1],'legacy trip restored by Departure');
console.log('PASS: legacy journey identity falls back to person plus departure, not vehicle alone');

const shared=trip('handoff-person:trip:0001',10,30), later=trip('handoff-person:trip:0002',40,50);
const handoffRecords=[segment('first-vehicle','handoff-person',shared,10,20,0,10),
  segment('second-vehicle','handoff-person',shared,20,30,10,20),
  segment('second-vehicle','handoff-person',later,40,50,0,20)];
const handoff=harness(handoffRecords);handoff.seek(15);handoff.click(handoffRecords[0]);
visible(handoff,[1,2,1,1],'one person journey represented by two vehicles');
handoff.seek(25);visible(handoff,[2,1,1,1],'selection follows same journey through vehicle handoff');
assert.ok(handoff.text().includes('Vehiculo: second-vehicle'));
assert.ok(handoff.text().includes(shared.Trip_ID));
handoff.seek(30);hidden(handoff,'handoff journey arrival');
handoff.seek(45);hidden(handoff,'handoff second vehicle next trip is not selected');
handoff.seek(15);visible(handoff,[1,2,1,1],'reverse seek restores first vehicle within same journey');
assert.ok(handoff.text().includes('Vehiculo: first-vehicle'));
console.log('PASS: person and trip identity spans vehicle handoff without mixing the next journey');

assert.ok(!/ruta planificada|prediccion en vivo/i.test(h.evaluate('technicalHelpContent.innerHTML')));
assert.ok(h.evaluate('technicalHelpContent.innerHTML').includes('replay registrado'));
console.log('PASS: future geometry is described as recorded replay, not a planned route or live prediction');
