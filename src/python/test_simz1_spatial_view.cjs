const assert=require('node:assert/strict');
const Spatial=require('./simz1_spatial_view.js');
const identity={run_id:'spatial-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64)};
const spatial={schema_version:1,mode:'gateway-od',validated:true,identity,
  boundary:{type:'Polygon',coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[4,4],[6,4],[6,6],[4,6],[4,4]]]},
  allowed_links:['entry','exit','inside'],entry_gateways:{entry:{link_id:'entry'}},exit_gateways:{exit:{link_id:'exit'}},internal_links:['inside']};
const view=new Spatial(spatial,identity),native=JSON.stringify(spatial);
assert.throws(()=>new Spatial({...spatial,identity:{...identity,run_id:'other'}},identity),/identidad/);
assert.throws(()=>new Spatial({...spatial,validated:false},identity),/identidad/);
assert.throws(()=>new Spatial({...spatial,identity:{}},{}),/identidad/);
assert.throws(()=>new Spatial({...spatial,identity:{...identity,iteration:-1}},{...identity,iteration:-1}),/identidad/);
assert.throws(()=>new Spatial({...spatial,boundary:{type:'Polygon',coordinates:[[[0,0],[1,1],[2,2]]] }},identity),/Anillo/);
assert.throws(()=>new Spatial({...spatial,boundary:{type:'Polygon',coordinates:[[[0,0],[1,1],[2,2],[0,0]]] }},identity),/degenerado/);
assert.equal(view.contains([2,2]),true);assert.equal(view.contains([5,5]),false);assert.equal(view.contains([-1,2]),false);
assert.equal(view.contains([0,5]),true);assert.equal(view.contains([4,5]),true);
console.log('PASS: spatial identity, rings, exterior and hole membership');
const path=[[-1,5],[11,5]],source=JSON.stringify(path),pieces=view.clipPath(path);
assert.equal(pieces.length,2);
for(const [actual,expected] of [[pieces[0][0],[0,5]],[pieces[0].at(-1),[4,5]],[pieces[1][0],[6,5]],[pieces[1].at(-1),[10,5]]])
  assert.ok(actual.every((value,i)=>Math.abs(value-expected[i])<1e-10));
assert.equal(view.clipPath([[-2,-1],[-1,-1]]).length,0);
assert.equal(view.clipPath([[1,1],[3,1],[3,3]]).length,1);
assert.equal(JSON.stringify(path),source);assert.equal(JSON.stringify(spatial),native);
const paths=view.paths([{path,kind:'history'}]);assert.equal(paths.length,2);assert.ok(paths.every(row=>row.kind==='history'));
console.log('PASS: roads and selected routes clip both boundaries without bridging holes or changing source');
const body={vehicle:'v',Link_ID:'entry',position:[2,2],Visual_Body_Path:[[1.99,2],[2.01,2]],Visual_Body_Width_Meters:1.8};
assert.equal(view.markers([body]).length,1);
assert.equal(view.markers([{...body,position:[5,5]}]).length,0);
assert.equal(view.markers([{...body,Link_ID:'outside'}]).length,0);
const footprint={...body,position:[3,5],Visual_Body_Path:[[3,5],[7,5]]};
assert.strictEqual(view.markers([footprint])[0],footprint,'filter the centre without deforming or splitting the footprint');
assert.equal(view.positions([{position:[1,1],kind:'origin'},{position:[12,12],kind:'destination'}]).length,1);
console.log('PASS: supported centres and endpoint flags stay in the domain; rigid bodies retain dimensions');
const OD={od_type:'external-external',origin_link:'entry',destination_link:'exit',origin_gateway:'entry',destination_gateway:'exit',
  origin_zone:'synthetic-exterior-entry:entry',destination_zone:'synthetic-exterior-exit:exit',scope:'observed_z1_only',door_to_door_seconds:null,metadata_source:'synthetic_gateway_od'};
const trip={OD,Departure:86390,Arrival:null,Status:'censored',Censored_At_Day_End:true};
const before=JSON.stringify(trip),text=view.tripText(trip,86400,String);
assert.match(text,/Tiempo transcurrido en tramo modelado Z1: 10/);
assert.match(text,/Tiempo completo en tramo modelado Z1: N\/D/);assert.match(text,/Tiempo puerta a puerta: N\/D/);
assert.equal(JSON.stringify(trip),before);
assert.throws(()=>view.validateTrip({...trip,OD:{...OD,origin_xy:[1,2]}}),/OD espacial/);
assert.throws(()=>view.validateTrip({...trip,OD:{...OD,origin_gateway:'exit'}}),/Zona\/puerta/);
assert.match(view.tripText({...trip,Departure:0,Arrival:12,Status:'completed',Censored_At_Day_End:false},5,String),/Tiempo completo en tramo modelado Z1: 12/);
const aborted=view.tripText({...trip,Departure:10,Abort:100,Status:'aborted',Censored_At_Day_End:false},200,String);
assert.match(aborted,/Tiempo transcurrido en tramo modelado Z1: 90 \(abortado; tiempo observado\)/);
assert.match(aborted,/Tiempo completo en tramo modelado Z1: N\/D/);
assert.match(view.tripText({...trip,Departure:10,Observation_End:80},200,String),/Tiempo transcurrido en tramo modelado Z1: 70/);
const nextDay=view.tripText({...trip,Arrival:90000,Status:'completed',Censored_At_Day_End:false},86400,String);
assert.match(nextDay,/Tiempo transcurrido en tramo modelado Z1: 10 \(censurado/);
assert.match(nextDay,/Tiempo completo en tramo modelado Z1: N\/D/);
console.log('PASS: exterior labels have no coordinates; censored trip retains null arrival and unknown complete/door-to-door duration');
const v2=new Spatial({...spatial,od_contract:'simz1-four-od-v2'},identity);
const observed={OD:{...OD,od_class:'EXTERNAL_EXTERNAL_THROUGH'},Departure:0,Arrival:25,Status:'completed',
  System_Entry:3,System_Exit:20,Observed_Duration_Seconds:17};
assert.match(v2.tripText(observed,25,String),/Tiempo completo en tramo modelado Z1: 17/);
assert.match(v2.tripText(observed,8,String),/Tiempo transcurrido en tramo modelado Z1: 5/);
assert.match(v2.tripText({...observed,System_Entry:null,System_Exit:null},8,String),/sin entrada observada/);
assert.throws(()=>v2.validateTrip({...observed,OD}),/OD espacial/);
assert.throws(()=>v2.validateTrip({...observed,OD:{...OD,od_class:'INTERNAL_INTERNAL'}}),/OD espacial/);
console.log('PASS: explicit four OD classes retain native observed entry/exit duration and legacy compatibility');
const balanced={...spatial,schema_version:2,mode:'balanced-gateway-v1',
  postprocessor_contract_version:'balanced-replay-contract-v1',visual_scope:'full_native_network_preserving_anchors_and_services',
  visual_link_ids:['entry','exit','inside','bus-only'],observation_end_seconds:108000,
  entry_gateways:{entry:{id:'entry-zone',crossing_link:'entry',observation_link:'inside'}},
  exit_gateways:{exit:{id:'exit-zone',crossing_link:'exit',observation_link:'inside'}}};
const bv=new Spatial(balanced,identity);
assert.throws(()=>new Spatial({...balanced,visual_link_ids:['inside']},identity),/sin respaldo/);
assert.throws(()=>new Spatial({...balanced,postprocessor_contract_version:'unverified'},identity),/sin respaldo/);
assert.deepEqual(bv.clipPath(path),[path],'native anchor geometry outside the polygon remains visible');
assert.equal(bv.markers([{...body,position:[-1,5]}]).length,1);
assert.equal(bv.markers([{...body,Link_ID:'unknown',position:[-1,5]}]).length,0);
const bod={...OD,od_class:'EXTERNAL_EXTERNAL_THROUGH',origin_zone:'entry-zone',destination_zone:'exit-zone',
  scope:'observed_z1_and_declared_anchors_only',metadata_source:'simz1-private-gateway-trip-v1',
  route_link_ids:['entry','inside','exit'],body_length_m:4.5,minimum_gap_m:.1,
  entry_crossing_link:'entry',exit_crossing_link:'exit',origin_observation_link:'inside',destination_observation_link:'inside'};
const bt={OD:bod,Departure:86390,Arrival:90000,System_Entry:86391,System_Exit:89999,Status:'completed'};
assert.equal(bv.validateTrip(bt),bod);
assert.match(bv.tripText(bt,90000,String),/Tiempo completo en tramo modelado Z1: 3608/);
for(const change of [{origin_zone:'wrong'},{entry_crossing_link:'wrong'},{minimum_gap_m:0},
  {route_link_ids:['entry','bus-only','exit']},{origin_xy:[0,0]}])
  assert.throws(()=>bv.validateTrip({...bt,OD:{...bod,...change}}));
const ft={Person_ID:'truck',Trip_Index:1,Trip_ID:'truck:trip:0001',Departure:80000,
  Freight:{vehicle_id:'truck',route_id:'f1',planned_departure:80000,route_link_ids:['bus-only'],roster_source:{sha256:'a'.repeat(64)}}};
assert.equal(bv.validateTrip(ft),ft.Freight);
assert.throws(()=>bv.validateTrip({...ft,Person_ID:'other'}),/Carga/);
assert.throws(()=>bv.validateTrip({...ft,Freight:{...ft.Freight,roster_source:{}}}),/Carga/);
assert.throws(()=>bv.validateTrip({...ft,Freight:{...ft.Freight,route_link_ids:['unknown']}}),/Carga/);
console.log('PASS balanced native anchors/services, OD/roster identity negatives, independent 30-hour observation');
