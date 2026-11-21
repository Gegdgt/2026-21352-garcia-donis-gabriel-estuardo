'use strict';
const assert=require('node:assert/strict');
const {SimZ1AggregateView}=require('./simz1_aggregate_view.js');
const identity={run_id:'aggregate-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64),source_version:'b'.repeat(64),visual_policy:'partial-native-v1',checkpoint_library_root:'fixture-root'};
const geometry={source:{path:[[0,0],[.001,0]],osm_tags:{name:'Origen de prueba'}},road:{path:[[.001,0],[.002,0]],osm_tags:{name:'Enlace de prueba'}}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function documentMock(){
  function element(tag){
    let text='';return {tagName:tag.toUpperCase(),children:[],attributes:{},value:'',hidden:false,style:{},
      append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}},
      setAttribute(k,v){this.attributes[k]=String(v);},
      replaceChildren(...nodes){this.children=[];text='';this.append(...nodes);},
      set textContent(value){text=String(value);this.children=[];},
      get textContent(){return text+this.children.map(n=>n.textContent).join('');}};
  }
  const host=element('div');host.id='simz1-controls';
  const find=(id,node=host)=>node.id===id?node:node.children.map(n=>find(id,n)).find(Boolean);
  return {createElement:element,getElementById:find,host};
}
function payload(time,changes={}){
  return {schema_version:1,identity:{...identity},time_seconds:time,time,no_positions:true,
    coverage:{position_available:false,association:'native_link_membership',unassociated_active:{carro:2,moto:0}},
    origins:[{origin_link:'source',family:'carro',scheduled_total:20,scheduled_due:12,requested:10,entered:4,
      waiting_admission:6,retired_waiting:0,arrived:1,active_origin_cohort:3,oldest_pending_request:10,latest_entry:20,
      hourly:[{hour:0,scheduled:12,requested:10,entered:4,arrived:1,waiting_admission_end:6}]},
      {origin_link:'source',family:'moto',scheduled_total:10,scheduled_due:8,requested:8,entered:3,
       waiting_admission:5,retired_waiting:0,arrived:1,active_origin_cohort:2,oldest_pending_request:12,latest_entry:21,
       hourly:[{hour:0,scheduled:8,requested:8,entered:3,arrived:1,waiting_admission_end:5}]}],
    links:[{link_id:'road',active_count:5,families:{carro:3,moto:2},last_change_time:21,
      time_since_change:time-21,latest_entry:21,latest_leave:19,entry_count:12,leave_count:7}],...changes};
}
function harness(){
  const document=documentMock(),pending=[],changes=[];
  const fetch=async(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject}));
  const view=new SimZ1AggregateView({identity,geometry,document,fetch,onChange:()=>changes.push(view?.status)});
  class PathLayer{constructor(props){this.id=props.id;this.props=props;}}
  const deck={PathLayer};
  const reply=(n,data,status=200)=>pending[n].resolve({ok:status===200,status,json:async()=>data});
  return {view,document,pending,changes,deck,reply};
}
async function main(){
  // Native association survives zero body coverage. Every graphical primitive
  // is a network path, not a vehicle proxy or an estimated position.
  const h=harness();h.view.update(390.8,{paused:true});
  assert.equal(h.pending.length,1);assert.match(h.pending[0].url,/time=390(?:&|$)/);
  assert.match(h.pending[0].url,/visual_policy=partial-native-v1/);assert.match(h.pending[0].url,/checkpoint_library_root=fixture-root/);
  h.reply(0,payload(390));await flush();
  assert.equal(h.view.status,'ready');assert.equal(h.view.snapshot().vehicle_markers_created,0);
  const layers=h.view.layers(h.deck);
  assert.deepEqual(layers.map(l=>l.id),['simz1-aggregate-links','simz1-aggregate-origins']);
  assert.equal(layers[0].props.data[0].count,5);assert.equal(layers[1].props.data[0].count,11);
  assert.ok(layers.every(l=>l.props.data.every(r=>r.path&&!('position' in r)&&!('vehicle' in r))));
  assert.match(h.document.host.textContent,/Datos al 00:06:30/);
  assert.match(h.document.host.textContent,/Activos sin enlace verificable: 2/);
  assert.match(h.document.host.textContent,/no posiciones ni cuerpos/);
  h.view.select('origin','source');assert.match(h.document.host.textContent,/Solicitudes/);
  assert.match(h.document.host.textContent,/Pendientes al corte/);
  assert.match(h.document.host.textContent,/00:00:10/);assert.match(h.document.host.textContent,/pueden estar en otros enlaces/);
  h.view.select('link','road');assert.match(h.document.host.textContent,/00:00:19/);
  assert.match(h.document.host.textContent,/Salidas registradas del enlace: 7/);
  assert.match(h.document.host.textContent,/no prueba inmovilidad corporal/);
  assert.match(h.document.host.textContent,/Indicador de asociación persistente: Sí/);
  assert.equal(h.view.persistence({...payload(390).links[0],time_since_change:299}),false);
  assert.equal(h.view.persistence({...payload(390).links[0],time_since_change:300}),true);
  assert.equal(h.view.persistence({...payload(390).links[0],time_since_change:null}),null);
  assert.equal(h.view.persistence({active_count:0,families:{},time_since_change:300}),false);

  // Family filters affect counts, never create missing bodies. An exact route
  // filter cannot be silently presented as filtered aggregate evidence.
  h.view.update(390.8,{paused:true,family:'motorcycle'});
  assert.equal(h.view.layers(h.deck)[0].props.data[0].count,2);
  assert.equal(h.view.layers(h.deck)[1].props.data[0].count,5);
  assert.equal(h.pending.length,1);
  h.view.update(390.8,{paused:true,family:'private',route:'route-unknown'});
  assert.ok(h.view.layers(h.deck).every(l=>l.props.data.length===0));
  assert.match(h.document.host.textContent,/Sin desglose agregado para la ruta elegida/);
  h.view.update(390.8,{paused:true,family:'all'});
  const checkbox=h.document.getElementById('simz1-aggregate-origins');checkbox.checked=false;checkbox.onchange();
  assert.equal(h.view.layers(h.deck)[1].props.data.length,0);assert.equal(h.view.layers(h.deck)[0].props.data.length,1);

  // Playback coalesces the minute, pause requests the exact native second.
  const throttle=harness();for(let t=60;t<120;t+=.25)throttle.view.update(t,{paused:false});
  assert.equal(throttle.pending.length,1);throttle.reply(0,payload(60));await flush();
  throttle.view.update(119.7,{paused:true});assert.equal(throttle.pending.length,2);
  throttle.reply(1,payload(119));await flush();assert.equal(throttle.view.data.time_seconds,119);
  throttle.view.update(60,{paused:true});assert.equal(throttle.pending.length,2);assert.equal(throttle.view.metrics.cacheHits,1);

  // A slow server must not starve during playback. Only one flight survives
  // several new minute targets, then the latest target is requested once.
  const slow=harness();slow.view.update(60,{paused:false});
  slow.view.update(120,{paused:false});slow.view.update(180,{paused:false});
  assert.equal(slow.pending.length,1);assert.equal(slow.pending[0].options.signal.aborted,false);
  slow.reply(0,payload(60));await flush();
  assert.equal(slow.view.data.time_seconds,60);assert.equal(slow.pending.length,2);
  assert.match(slow.pending[1].url,/time=180(?:&|$)/);
  assert.match(slow.document.host.textContent,/Datos al 00:01:00/);
  slow.view.update(240,{paused:false});assert.equal(slow.pending.length,2);
  assert.equal(slow.view.layers(slow.deck)[0].props.data[0].count,5);
  slow.view.update(245,{paused:true});assert.equal(slow.pending.length,3);
  assert.equal(slow.pending[1].options.signal.aborted,true);assert.equal(slow.view.data,null);
  slow.reply(2,payload(245));await flush();slow.reply(1,payload(180));await flush();
  assert.equal(slow.view.data.time_seconds,245);
  slow.view.seek(390);assert.equal(slow.view.data,null);
  slow.view.update(245,{paused:false});assert.equal(slow.pending.length,3);
  slow.view.update(390,{paused:false});assert.equal(slow.pending.length,4);
  slow.reply(3,payload(390));await flush();slow.view.update(391,{paused:false});
  assert.equal(slow.pending.length,4);assert.equal(slow.view.data.time_seconds,390);

  // An older response cannot repaint a newer selection, even if a transport
  // ignores cancellation and completes late with a valid old payload.
  const race=harness();race.view.update(390);race.view.update(510);
  assert.equal(race.pending[0].options.signal.aborted,true);assert.equal(race.pending.length,2);
  race.reply(1,payload(510));await flush();race.reply(0,payload(390));await flush();
  assert.equal(race.view.data.time_seconds,510);assert.equal(race.view.metrics.stale,1);

  // Wrong run/version/time, invalid counters and server errors fail closed.
  // Retry is one explicit request; rendering the same failed time never loops.
  const bad=harness();bad.view.update(600);bad.reply(0,payload(600,{identity:{...identity,run_id:'other'}}));await flush();
  assert.equal(bad.view.status,'error');assert.ok(bad.view.layers(bad.deck).every(l=>l.props.data.length===0));
  for(let i=0;i<10;i++)bad.view.update(600);
  bad.view.update(720,{paused:false});assert.equal(bad.pending.length,1);
  bad.view.update(600);assert.equal(bad.pending.length,1);bad.view.retry.onclick();assert.equal(bad.pending.length,2);
  bad.reply(1,payload(600));await flush();assert.equal(bad.view.status,'ready');assert.equal(bad.view.retry.hidden,true);
  for(const invalid of [payload(600,{identity:{...identity,source_version:'c'.repeat(64)}}),payload(599),
    payload(600,{identity:{...identity,visual_policy:'other'}}),payload(600,{identity:{...identity,checkpoint_library_root:'other'}}),
    payload(600,{no_positions:false}),payload(600,{links:[{link_id:'road',active_count:5,families:{carro:6}}]})])
    assert.throws(()=>SimZ1AggregateView.validate(invalid,identity,600));
  const balance=payload(600);balance.origins[0].waiting_admission=0;
  assert.throws(()=>SimZ1AggregateView.validate(balance,identity,600));
  const retired=payload(600);retired.origins[0].waiting_admission=4;retired.origins[0].retired_waiting=2;
  assert.equal(SimZ1AggregateView.validate(retired,identity,600),retired);
  const baseIdentity={...identity};delete baseIdentity.visual_policy;delete baseIdentity.checkpoint_library_root;
  assert.throws(()=>SimZ1AggregateView.validate(payload(600),baseIdentity,600));
  bad.view.update(660);bad.reply(2,null,503);await flush();assert.equal(bad.view.status,'error');
  assert.equal(bad.view.snapshot().vehicle_markers_created,0);

  // Missing location remains missing; no origin glyph is fabricated. Missing
  // optional hourly arrivals remain visible as unknown, never an invented zero.
  const unknown=harness();unknown.view.update(720);
  const data=payload(720);data.origins[0].origin_link=null;delete data.origins[1].hourly;
  data.origins[1].hourly=[{hour:0,scheduled:8,requested:8,entered:3}];
  unknown.reply(0,data);await flush();assert.equal(unknown.view.status,'ready');
  assert.equal(unknown.view.layers(unknown.deck)[1].props.data.length,1);
  unknown.view.select('origin','source');assert.match(unknown.document.host.textContent,/Sin dato/);
  assert.equal(unknown.view.snapshot().vehicle_markers_created,0);
  console.log('PASS aggregate UI: DOM controls, geometry-only layers, counts, filters, time coalescing, cache, stale responses, invalid identity, balance and explicit retry. No browser/WebGL exercised.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
