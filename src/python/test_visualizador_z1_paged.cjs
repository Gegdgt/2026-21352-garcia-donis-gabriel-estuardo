// Real controls, a small DOM stub and deferred requests: no WebGL/FPS claim.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('python/visualizador_z1_controls.js','utf8');
const selectedLayers=['selected-history','selected-future','selected-origin','selected-destination'];
function element(tag='div') {
  const children=[];
  const node={tagName:tag.toUpperCase(),style:{},children,open:false,
    append(...nodes){children.push(...nodes);},appendChild(child){children.push(child);},setAttribute(){},
    contains(other){return other===node || children.some(child=>child.contains?.(other));}};
  return node;
}
function record(vehicle,person,id,start,end,from,to,departure=86390,arrival=86430) {
  return {vehicle,Agent_ID:person,Link_ID:id,Replay_Journey_Key:vehicle==='a'?'a'.repeat(64):'b'.repeat(64),
    Trip:{Trip_ID:person+':trip:0001',Departure:departure,Arrival:arrival,
      Origin_Position:[0,0],Destination_Position:[40,0],Status:'completed'},
    path:[[from,0],[to,0]],timestamps:[start,end],Speed_kmh:3.6,Max_Speed_kmh:43.2,
    Motion_Plan:{version:1,status:'constant',distance_m:to-from,cap_mps:12,phases:[[start,end,0,1,0]]}};
}
const a0=record('a','p-a','a0',86390,86400,0,10);
const a1=record('a','p-a','a1',86400,86420,10,30);
const a2=record('a','p-a','a2',86420,86430,30,40);
const b=record('b','p-b','b0',86400,86420,0,20,86400,86420);
function harness() {
  const requests=[];
  const layer=id=>({id,props:{data:[]},clone(props){return {...this,props:{...this.props,...props}};}});
  const layers=['trips',...selectedLayers].map(layer);
  const config={hud:{run_id:'explicit-run-100000',iteration:0,planned_persons:100000,planned_trips:100000,
      demand_seed:17,matsim_seed:17,observed_departures:100000},
    replay_window:{start_seconds:86400,end_seconds:86420},
    pagination:{block_index:1,block_count:3,index_url:'../index.html',journey_endpoint:'../api/journey',
      total_reconstructed_vehicles:100000,total_segments:6000000,loaded_segments:2,
      blocks:[{index:0,start_seconds:86380,end_seconds:86400,url:'0000.html'},
              {index:1,start_seconds:86400,end_seconds:86420,url:'0001.html'},
              {index:2,start_seconds:86420,end_seconds:86440,url:'0002.html'}]}};
  const sandbox={URLSearchParams,AbortController,console,performance:{now:()=>0},requestAnimationFrame(){},
    config,replaySegments:[structuredClone(a1),structuredClone(b)],incidentRecords:[],layers,
    window:{location:{href:''}},document:{hidden:false,createElement:element,body:element('body'),addEventListener(){}},
    fetch(url,options){return new Promise(resolve=>requests.push({url,options,resolve}));},
    deckInstance:{props:{layers},setProps(props){Object.assign(this.props,props);}}};
  vm.createContext(sandbox);vm.runInContext(source,sandbox);
  const evaluate=code=>vm.runInContext(code,sandbox);
  return {sandbox,requests,evaluate,
    click(index){evaluate(`deckInstance.props.onClick({object:${index==null?'null':`replaySegments[${index}]`}})`);},
    seek(time){evaluate(`seeker.value=${time};seeker.oninput()`);},
    count(id){return evaluate(`layers.find(layer=>layer.id===${JSON.stringify(id)}).props.data.length`);},
    reply(index,records,overrides={}) {
      const request=requests[index],key=new URL(request.url,'http://127.0.0.1/blocks/0001.html').searchParams.get('key');
      request.resolve({ok:true,json:async()=>({run_id:config.hud.run_id,iteration:0,key,records,...overrides})});
    }};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const h=harness();h.seek(86410);h.click(0);
  assert.equal(h.evaluate('activeAgentCount'),2);
  assert.equal(h.evaluate('technicalHelp.open'),false);
  assert.ok(h.evaluate('totalAgents.textContent').includes('Vehiculos en bloque: 2'));
  assert.ok(h.evaluate('totalAgents.textContent').includes('Total replay: 100,000'));
  assert.ok(h.evaluate('technicalStats.textContent').includes('Personas planificadas: 100000 | Viajes planificados: 100000'));
  assert.ok(h.evaluate('clock.textContent').startsWith('24:00:10 (dia 2)'));
  assert.equal(h.evaluate('replaySegments[0].Max_Speed_kmh'),43.2,'preserve earlier complete-journey maximum');
  assert.equal(h.count('selected-history'),0,'no partial history while complete trip loads');
  assert.equal(h.count('selected-future'),0);
  assert.equal(h.count('selected-origin'),1);assert.equal(h.count('selected-destination'),1);
  assert.ok(h.evaluate('info.textContent').includes('Consultando recorrido completo'));
  assert.ok(h.requests[0].url.includes('run_id=explicit-run-100000'));
  assert.ok(h.requests[0].url.includes('iteration=0'));
  h.reply(0,[a0,a1,a2]);await flush();
  assert.equal(h.count('selected-history'),2);assert.equal(h.count('selected-future'),2);
  assert.ok(h.evaluate('info.textContent').includes('Recorrido completo del viaje cargado'));
  assert.equal(h.evaluate('selectedHistory[0].timestamps[0]'),86390);
  assert.equal(h.evaluate('selectedHistory[2].timestamps[1]'),86430);
  assert.equal(h.count('trips'),2,'fetching full route must not expand the active marker index');
  h.seek(86400);assert.equal(h.count('selected-history'),1);
  assert.equal(h.count('selected-future'),2);
  assert.equal(h.evaluate('markerAt(replaySegments[0],86400).position[0]'),10);
  h.seek(86420);
  assert.ok(h.evaluate('current')<86420 && h.evaluate('current')>86420-1e-7,'pause strictly before exclusive edge');
  assert.equal(h.evaluate('paused'),true);
  assert.equal(h.count('trips'),2,'no false disappearance at the edge of a continuing journey');
  assert.equal(h.count('selected-history'),2);assert.equal(h.count('selected-future'),2);
  h.seek(86410);h.click(0);assert.equal(h.requests.length,1,'only selected complete journey cached');
  console.log('PASS: explicit 100k identity/counts, midnight block edge, complete-history lookup, original kinematics and bounded active index');
  const edge=harness();edge.evaluate('animate(0);animate(1000)');
  assert.equal(edge.evaluate('paused'),true,'120x stops at the block edge instead of looping');
  assert.ok(edge.evaluate('current')>86419.9999999 && edge.evaluate('current')<86420);
  const endpoint=edge.evaluate('current');edge.evaluate('animate(500000)');
  assert.equal(edge.evaluate('current'),endpoint,'edge remains paused until explicit navigation/seek');

  const stale=harness();stale.seek(86410);stale.click(0);stale.click(1);
  assert.equal(stale.requests[0].options.signal.aborted,true);
  stale.reply(0,[a0,a1,a2]);await flush();
  assert.equal(stale.count('selected-history'),0,'old selected journey response must not replace new selection');
  assert.ok(stale.evaluate('info.textContent').includes('p-b:trip:0001'));
  stale.reply(1,[b]);await flush();
  assert.equal(stale.evaluate('fullJourneyKey'),stale.evaluate('tripKey(replaySegments[1])'));
  assert.equal(stale.count('selected-history'),1);
  stale.click(0);stale.click(null);stale.reply(2,[a0,a1,a2]);await flush();
  assert.equal(stale.evaluate('pinned'),null);
  for(const id of selectedLayers)assert.equal(stale.count(id),0);
  assert.equal(stale.evaluate('info.style.display'),'none');
  console.log('PASS: aborted/stale asynchronous responses never revive a different or cleared selection');

  const mismatch=harness();mismatch.seek(86410);mismatch.click(0);
  mismatch.reply(0,[a0,a1,a2],{run_id:'another-run'});await flush();
  assert.equal(mismatch.count('selected-history'),0);assert.equal(mismatch.count('selected-future'),0);
  assert.ok(mismatch.evaluate('info.textContent').includes('no corresponde a la corrida'));
  assert.equal(mismatch.count('trips'),2,'native block remains visible after lookup failure');
  const nav=mismatch.evaluate("hud.children.find(child=>child.className==='simz1-block-navigation')");
  assert.equal(nav.children[0].href,'../index.html');
  const choose=nav.children[1].children[0];
  assert.equal(choose.children.length,3);
  assert.equal(choose.children[1].selected,true);
  choose.value='0002.html';choose.onchange();
  assert.equal(mismatch.sandbox.window.location.href,'0002.html');
  console.log('PASS: wrong-run lookup rejected with honest unavailable route; native markers survive; explicit block navigation');
})().catch(error=>{console.error(error);process.exitCode=1;});
