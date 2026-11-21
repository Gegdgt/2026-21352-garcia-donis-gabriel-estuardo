// Prepared pure tests. No browser, WebGL, server, replay windows or file writes.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const Stops=require('./simz1_transit_stops.js');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/simz1-stop-signs-synthetic.json'),'utf8'));
const clone=()=>structuredClone(fixture),identity=fixture.identity;
class Layer {constructor(props){this.id=props.id;this.props=props;}clone(props){return new Layer({...this.props,...props});}}
const deck={IconLayer:Layer,PathLayer:Layer,TextLayer:Layer};
const input=clone(),original=JSON.stringify(input),model=new Stops(input,identity);
assert.deepEqual(model.records.map(row=>row.icon),['green','mixed-transfer','blue']);
assert.equal(model.records.find(row=>row.stop_id==='synthetic-west').services[0].system,'tubus');
for(const system of ['transurbano','urbano','extraurbano']) {
  const data=clone();data.records[1].services[0].system=system;
  assert.equal(new Stops(data,identity).records.find(row=>row.stop_id==='synthetic-west').icon,'blue');
}
assert.strictEqual(Stops.atlas(),Stops.atlas(),'one shared atlas for all instances');
assert.equal(Object.keys(Stops.atlas().mapping).length,27);
assert.ok(Object.values(Stops.atlas().mapping).every(tile=>tile.x+tile.width<=864 && tile.y+tile.height<=216));
assert.match(decodeURIComponent(Stops.atlas().url),/rect/,'stop sign is rectangular, not a signal lamp');
let layers=model.layers(deck,15);
assert.equal(layers.length,3);assert.equal(model.snapshot().represented,3);
assert.ok(model.data.some(row=>row.transfer),'explicit interchange remains visible at low zoom');
layers=model.updateLayers(layers,16);assert.equal(model.data.length,3);
const same=model.updateLayers(layers,15.9);assert.strictEqual(same,layers,'hysteresis and reuse within same band');
layers=model.updateLayers(layers,15.6);assert.match(model.snapshot().display_mode,/clusters/);
layers=model.updateLayers(layers,18);assert.equal(model.labels.length,3);
const signs=layers.find(layer=>layer.id==='transit-stop-signs');
assert.equal(signs.props.sizeMaxPixels,50);assert.equal(signs.props.billboard,true);assert.equal(signs.props.getAngle,0);
assert.equal(signs.props.sizeUnits,'pixels');
const eastSign=model.records.find(row=>row.stop_id==='synthetic-east'),westSign=model.records.find(row=>row.stop_id==='synthetic-west');
assert.equal(signs.props.getIcon(eastSign),'green-left');assert.equal(signs.props.getIcon(westSign),'blue-right');
for(const row of [eastSign,westSign])assert.equal(Stops.atlas().mapping[signs.props.getIcon(row)].anchorX,48,'leader tip anchors stay identical');
assert.equal(layers.find(layer=>layer.id==='transit-stop-names').props.pickable,false);
assert.equal(signs.props.parameters.depthWriteEnabled,false);
assert.equal(model.arrows.length,3);
const east=model.arrows.find(row=>row.stop_id==='synthetic-east').path;
const west=model.arrows.find(row=>row.stop_id==='synthetic-west').path;
assert.ok(east[1][0]>east[0][0] && west[1][0]<west[0][0],'opposite directed accesses keep opposite world arrows');
assert.equal(JSON.stringify(input),original,'zoom and geometry derivation preserve source records');
assert.match(Stops.tooltip(model.records.find(row=>row.stop_id==='synthetic-west')).text,/TuBus · F2 → Oeste/);
assert.match(Stops.tooltip(model.records.find(row=>row.transfer)).text,/Transbordo documentado/);
assert.equal(Stops.tooltip({system_id:'signal'}),null,'traffic lights are not stops');
const spatial={allowed:new Set(['east']),contains:p=>p[0]<0.0005};
const clipped=new Stops(clone(),identity,spatial);
assert.equal(clipped.records.length,1);assert.equal(clipped.issues.length,2);
const bad=clone();bad.records[0].position=[NaN,0];bad.records[1].services[0].system='unknown';
assert.equal(new Stops(bad,identity).records.length,1);
assert.equal(new Stops(clone(),{...identity,run_id:'another-run'}).records.length,0);
assert.equal(new Stops(null,identity).layers(deck,19).length,3);
assert.equal(new Stops({...clone(),records:[null]},identity).snapshot().issues[0].reason,'invalid_stop_record');
assert.equal(new Stops({...clone(),records:{}},identity).snapshot().issues[0].reason,'invalid_stop_records');
assert.equal(new Stops({available:false,issues:[{reason:'approved_domain_missing'}]},identity).snapshot().accepted,0);
const coincident=clone();coincident.records[1].position=[...coincident.records[0].position];
assert.equal(new Stops(coincident,identity).records.length,3,'never merge opposed platforms or transfer sites by proximity');

const annotation=clone();
for(const row of annotation.records) {
  delete row.Link_ID;delete row.bearing_degrees;delete row.direction;
  row.annotation_kind='catalog_only';row.native_access_status='unmapped';
  row.coordinate_evidence={element:row.stop_id,timestamp:'synthetic'};
  row.simulation_usage={status:'not_configured',used_by_simulation:false};
}
const catalog=new Stops(annotation,identity,{allowed:new Set(),contains:()=>true});
assert.equal(catalog.records.length,3,'catalog platforms do not require a fabricated native lane');
catalog.layers(deck,18);assert.equal(catalog.arrows.length,0,'no inferred arrow from source route endpoints');
const tip=Stops.tooltip(catalog.records[0]).text;
assert.match(tip,/Operador:/);assert.match(tip,/no tiene transporte público configurado/);
assert.match(tip,/carril MATSim sin asociar/);
annotation.records[0].Link_ID='invented';
assert.equal(new Stops(annotation,identity).records.length,2,'catalog cannot masquerade as mapped native stop');

const many=clone();many.records=Array.from({length:600},(_,i)=>({...structuredClone(fixture.records[i%3]),
  stop_id:'synthetic-load-'+String(i).padStart(4,'0'),transfer:null,opposed_stop_ids:[],
  position:[-90.513+(i%30)*.00006,14.64+Math.floor(i/30)*.00006]}));
// One documented interchange is protected from spatial aggregation.
many.records[0].transfer={id:'synthetic-hub',name:'Synthetic transfer'};
const crowd=new Stops(many,identity),anchors=JSON.stringify(crowd.records.map(r=>r.position));
let crowdLayers=crowd.layers(deck,14),cached=crowd.data;
assert.ok(crowd.data.length<60,'hundreds of nearby platforms group at low zoom');
assert.equal(crowd.snapshot().represented,600,'every platform survives grouping');
assert.ok(crowd.data.includes(crowd.records[0]),'transfer survives as its own marker');
for(const group of crowd.data.filter(r=>r.display_cluster)) {
  assert.strictEqual(group.position,group.members[0].position,'cluster anchor is a real member, never a centroid');
  assert.match(Stops.tooltip(group).text,/Agrupación visual/);
}
for(const pitch of [0,60])for(const bearing of [0,90,180,270]) {
  // The stop layer consumes zoom only: deck billboard handles pitch/bearing.
  assert.strictEqual(crowd.updateLayers(crowdLayers,14),crowdLayers,`camera ${pitch}/${bearing} reuses buffers`);
}
crowdLayers=crowd.updateLayers(crowdLayers,18);assert.equal(crowd.data.length,600);
assert.equal(crowdLayers.length,3,'constant instanced layer count');
crowdLayers=crowd.updateLayers(crowdLayers,22);
assert.ok(crowd.data.every(r=>crowdLayers[1].props.getSize(r)<=50),'size capped at maximum zoom');
crowdLayers=crowd.updateLayers(crowdLayers,14);assert.strictEqual(crowd.data,cached,'reuse cached aggregates');
assert.equal(JSON.stringify(crowd.records.map(r=>r.position)),anchors,'camera and zoom never relocate platforms');
console.log('PASS: stop colors, catalog/native separation, operators, transfers, source anchors, zoom grouping, 600 instances and buffer reuse');
