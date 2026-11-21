// Stateless motion evaluation: analytic phases are the oracle, not animation frames.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('python/visualizador_z1_controls.js','utf8');
function harness(records,configuration={}) {
  let timestamp=0;
  const layer=id=>({id,props:{data:[]},clone(props){return {...this,props:{...this.props,...props}};}});
  const layers=['trips','selected-history','selected-future','selected-origin','selected-destination'].map(layer);
  const sandbox={window:{},console,performance:{now:()=>timestamp},requestAnimationFrame(){},
    document:{hidden:false,createElement(){return {style:{},append(){},setAttribute(){}};},body:{appendChild(){}},addEventListener(){}},
    config:configuration,replaySegments:records,incidentRecords:[],layers,
    deckInstance:{props:{layers},setProps(props){Object.assign(this.props,props);}}};
  vm.createContext(sandbox);vm.runInContext(source,sandbox);
  const evaluate=code=>vm.runInContext(code,sandbox);
  return {sandbox,evaluate,clock:value=>{timestamp=value;},
    seek(time){evaluate(`seeker.value=${time};seeker.oninput()`);},
    marker(index,time){return evaluate(`markerAt(replaySegments[${index}],${time})`);},
    rendered(){return evaluate("layers.find(layer=>layer.id==='trips').props.data[0]");},
    select(index){evaluate(`deckInstance.props.onClick({object:replaySegments[${index}]})`);}};
}
function segment(id,start,end,path,plan,trip) {
  return {vehicle:'vehicle',Agent_ID:'person',Link_ID:id,path,timestamps:[start,end],Trip:trip,
    Speed_kmh:plan.distance_m/(end-start)*3.6,Motion_Speed_kmh:99,Movement_End:end,
    Motion_Plan:{version:1,source:'synthetic_analytic_fixture',status:'kinematic',fallback_reason:null,...plan},
    Observed_Waits:{},Wait_Evidence:'estimated_residual_unknown_cause'};
}
function near(actual,expected,label,tolerance=1e-8){assert.ok(Math.abs(actual-expected)<tolerance,`${label}: ${actual} != ${expected}`);}
function vector(value){return Array.from(value);}
const trip={Trip_ID:'person:trip:0001',Departure:1000,Arrival:1035,Origin_Position:[0,0],Destination_Position:[200,400]};
const approach=segment('approach',1000,1020,[[0,0],[100,200]],{
  distance_m:100,phases:[[1000,1005,0,10,0],[1005,1015,50,10,-1],[1015,1020,100,0,0]]},trip);
const departure=segment('departure',1020,1035,[[100,200],[200,400]],{
  distance_m:100,phases:[[1020,1030,0,0,1],[1030,1035,50,10,0]]},trip);
const h=harness([approach,departure]);

for(const [time,distance,speed] of [[1000,0,36],[1005,50,36],[1010,87.5,18],[1014,99.5,3.6],
                                  [1015,100,0],[1019,100,0],[1002,20,36],[1010,87.5,18]]){
  const marker=h.marker(0,time);
  near(marker.position[0],distance,'analytic distance at '+time);
  near(marker.position[1],distance*2,'same path fraction at '+time);
  near(marker.Visual_Speed_kmh,speed,'phase derivative at '+time);
  assert.equal(marker.Speed_kmh,18,'measured mean must not be overwritten');
  assert.equal(marker.Motion_Speed_kmh,99,'legacy exported field must not be overwritten');
}
for(const [time,distance,speed] of [[1020,0,0],[1022,2,7.2],[1025,12.5,18],[1030,50,36],[1034,90,36]]){
  const marker=h.marker(1,time);
  near(marker.position[0],100+distance,'departure integration at '+time);
  near(marker.Visual_Speed_kmh,speed,'departure acceleration at '+time);
}
for(const time of [1005.5,1009.5,1014.5]){
  const delta=1e-4,left=h.marker(0,time-delta),right=h.marker(0,time+delta);
  const derivative=(right.Visual_Distance_m-left.Visual_Distance_m)/(2*delta);
  near(derivative,h.marker(0,time).Visual_Speed_kmh/3.6,'position derivative',1e-7);
}
console.log('PASS: analytic v0*dt + 0.5*a*dt² position, derivative speed, progressive brake/start and preserved native means');

for(const time of [1015,1016,1019]){
  const marker=h.marker(0,time);
  assert.equal(marker.Waiting,true);assert.deepEqual(vector(marker.color),[255,255,255]);
  assert.deepEqual(vector(marker.position),[100,200]);
}
const ten=h.marker(0,1015-10/3.6);
near(ten.Visual_Speed_kmh,10,'slow 10 km/h');
assert.equal(ten.Waiting,false);assert.deepEqual(vector(ten.color),[245,65,65]);
assert.deepEqual(vector(h.marker(0,1014.999).color),[245,65,65]);
assert.deepEqual(vector(h.marker(0,1014.9999999).color),[255,255,255]);
assert.equal(h.evaluate('MOTION_STOP_TOLERANCE_KMH'),1e-4);
assert.ok(h.evaluate('technicalHelpContent.innerHTML').includes('0.0001 km/h'));
assert.ok(!h.evaluate('legend.innerHTML').includes('0.0001 km/h'),'numerical tolerance belongs in secondary help');
console.log('PASS: white only at numerical zero, slow 10 km/h red, stationary hold and documented tolerance');

for(const time of [1010,1018,1001,1025,1020,1010]){
  h.seek(time);h.select(0);
  const rendered=h.rendered();
  const expected=h.marker(time<1020?0:1,time);
  assert.deepEqual(vector(rendered.position),vector(expected.position));
  const history=h.evaluate("layers.find(layer=>layer.id==='selected-history').props.data");
  const future=h.evaluate("layers.find(layer=>layer.id==='selected-future').props.data");
  const endpoint=history.length ? history[history.length-1].path.at(-1) : null;
  if(endpoint)assert.deepEqual(vector(endpoint),vector(rendered.position),'history ends at same kinematic marker');
  if(future.length)assert.deepEqual(vector(future[0].path[0]),vector(rendered.position),'future begins at same marker');
}
for(const boundary of [1005,1015,1020,1030]){
  const index=boundary<1020?0:1;
  const marker=h.marker(index,boundary);
  const left=boundary===1020?h.marker(0,boundary-1e-6):h.marker(index,boundary-1e-6);
  near(marker.position[0],left.position[0],'continuous phase/link position',2e-5);
  near(marker.Visual_Speed_kmh,left.Visual_Speed_kmh,'continuous phase/link speed',1e-5);
}
console.log('PASS: marker, selected history and future share evaluation; phase and link boundaries stay continuous');

const one=harness([approach,departure]),fast=harness([approach,departure]);
one.clock(0);one.seek(1000);one.evaluate('realtime.onclick();animate(10000)');
fast.clock(0);fast.seek(1000);fast.evaluate('original.onclick();animate(10000/120)');
near(one.evaluate('current'),1010,'1x clock');near(fast.evaluate('current'),1010,'120x clock');
assert.deepEqual(vector(one.rendered().position),vector(fast.rendered().position));
near(one.rendered().Visual_Speed_kmh,fast.rendered().Visual_Speed_kmh,'1x/120x trajectory invariant');
one.clock(10000);one.evaluate('toggle.onclick()');
const paused=JSON.stringify(one.rendered());
one.evaluate('animate(500000);render();render()');
assert.equal(JSON.stringify(one.rendered()),paused,'pausing must freeze kinematics');
one.seek(1014);assert.equal(one.evaluate('paused'),true);near(one.rendered().Visual_Speed_kmh,3.6,'paused seek');
one.seek(1005);near(one.rendered().position[0],50,'reverse seek without previous velocity');
console.log('PASS: 1x/120x same absolute trajectory, paused redraw, paused seek and reverse seek');

const shift=86390-1000;
const midnight=JSON.parse(JSON.stringify(approach));
midnight.timestamps=midnight.timestamps.map(t=>t+shift);
midnight.Trip={...trip,Trip_ID:'night',Departure:86390,Arrival:86410};
midnight.Motion_Plan.phases=midnight.Motion_Plan.phases.map(([t0,t1,...rest])=>[t0+shift,t1+shift,...rest]);
const night=harness([midnight],{replay_window:{start_seconds:86380,end_seconds:86500}});
for(const time of [86400,86405,86395,86409,86400]){
  night.seek(time);
  near(night.rendered().position[0],h.marker(0,time-shift).position[0],'absolute midnight integration');
}
assert.ok(night.evaluate('clock.textContent').startsWith('24:00:00 (dia 2)'));
console.log('PASS: midnight retains absolute phase times and reverse seeking does not reset motion');

const fallback={...approach,Motion_Plan:{...approach.Motion_Plan,status:'fallback',feasible:false,
  fallback_reason:'infeasible_native_interval',phases:[[1000,1010,0,10,0],[1010,1020,100,0,0]]}};
const constant={...approach,Motion_Plan:{version:1,status:'constant',source:'fixture',distance_m:100,phases:[[1000,1020,0,5,0]]}};
const invalid={...approach,Movement_End:1010,Motion_Speed_kmh:36,Motion_Plan:{version:1,distance_m:100,phases:[[1000,1005,0,10,0],[1006,1020,50,0,0]]}};
const old={...approach,Motion_Plan:undefined,Movement_End:1020,Motion_Speed_kmh:10};
const unknown={...old,Motion_Speed_kmh:null,Speed_kmh:null,color:[255,255,255]};
const fall=harness([fallback]);fall.seek(1005);fall.select(0);
assert.equal(fall.rendered().Visual_Motion_Status,'fallback');
assert.ok(fall.evaluate('info.textContent').includes('interpolacion de respaldo'));
assert.ok(fall.evaluate('info.textContent').includes('infeasible_native_interval'));
assert.ok(fall.evaluate('info.textContent').includes('no velocidad instantanea medida'));
assert.ok(fall.evaluate('info.textContent').includes('Velocidad media medida del tramo: 18.0 km/h'));
for(const [fixture,status] of [[constant,'constant'],[old,'legacy']]){
  fall.sandbox.fixture=fixture;
  const marker=fall.evaluate('markerAt(fixture,1005)');
  assert.equal(marker.Visual_Motion_Status,status);
  assert.ok(marker.position.every(Number.isFinite));
  assert.equal(marker.Speed_kmh,18);
}
fall.sandbox.unknown=unknown;
const noSpeed=fall.evaluate('markerAt(unknown,1005)');
assert.equal(noSpeed.Visual_Speed_kmh,null);assert.equal(noSpeed.Waiting,false);
assert.notDeepEqual(vector(noSpeed.color),[255,255,255]);
fall.seek(1020);assert.equal(fall.evaluate("layers.find(layer=>layer.id==='trips').props.data.length"),0);
console.log('PASS: explicit fallback and provenance, legacy compatibility, unknown speed not white and exclusive segment end');

const unavailable={...approach,Motion_Plan:{version:1,status:'unavailable',distance_m:100,phases:[],
  fallback_reason:'distance_exceeds_cap_over_native_interval',source:'fixture'}};
const cappedInvalid={...approach,Motion_Plan:{...approach.Motion_Plan,cap_mps:5}};
for(const fixture of [unavailable,invalid,cappedInvalid]){
  const gap=harness([fixture]);gap.seek(1010);gap.select(0);
  assert.equal(gap.marker(0,1010),null);
  assert.equal(gap.evaluate("layers.find(layer=>layer.id==='trips').props.data.length"),0);
  assert.equal(gap.evaluate('activeAgentCount'),0);
  assert.equal(gap.evaluate('info.style.display'),'block','native trip metadata remains inspectable');
  assert.ok(gap.evaluate('info.textContent').includes('Velocidad media medida del tramo: 18.0 km/h'));
  assert.ok(gap.evaluate('info.textContent').includes('Movimiento visual: no disponible'));
  assert.ok(!gap.evaluate('info.textContent').includes('Velocidad visual estimada'));
  for(const time of [999,1000,1010,1020]){
    const route=gap.evaluate(`splitSelectedRoute(replaySegments,${time})`);
    assert.equal(route.history.length,0);assert.equal(route.future.length,0);
  }
}
console.log('PASS: unavailable/invalid/over-cap motion remains a visual gap, no trail shortcut, native metadata preserved');
