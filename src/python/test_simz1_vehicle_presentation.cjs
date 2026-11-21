// Prepared only: no browser, server, MATSim, population, SQLite or run files.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=['simz1_visual_lanes.js','simz1_visual_queues.js','simz1_vehicle_picking.js']
  .map(name=>fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n');
const [Catalog,Lanes,Queues,Picking]=vm.runInNewContext(source+
  '\n[SimZ1VehicleCatalog,SimZ1VisualLanes,SimZ1VisualQueues,SimZ1VehiclePicking]',{});
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/simz1-vehicle-presentation.json'),'utf8'));
const shell=fs.readFileSync(path.join(__dirname,'visualizador_z1_continuous.html'),'utf8');
const bodyLayer=shell.slice(shell.indexOf("id:'trips',data:[]"),shell.indexOf("id:'trips',data:[]")+600);
assert.match(bodyLayer,/getWidth:d=>d\.Visual_Body_Width_Meters/);
assert.match(bodyLayer,/widthUnits:'meters',widthMinPixels:0/,'no pixel floor inflates body geometry at distant zoom');
const plain=value=>JSON.parse(JSON.stringify(value)),near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale];
for(const test of fixture.aliases) {
  const input={...test.input,person_id:'keep-person',vehicle_id:'keep-vehicle',trip_id:'keep-trip'};
  const original=JSON.stringify(input),result=Catalog.resolve(input);
  assert.equal(result.label,test.label);assert.equal(result.family,test.family);
  assert.equal(result.driving_profile,test.profile);
  assert.equal(JSON.stringify(input),original,'aliases must not rename identities/types/profiles');
}
assert.equal(Catalog.resolve({Agent_Type:'TransportePublico'}).dimensions,null,'a passenger never acquires a bus');
assert.equal(Catalog.resolve({Vehicle_Type:'TransitBus',Transit_Operator:'operator',Transit_Service:'service'}).operator,'operator');
assert.equal(Catalog.resolve({Vehicle_Type:'TransitBus',Transit_Operator:'operator',Transit_Service:'service'}).service,'service');
for(const type of ['Normal','Motociclista','TransportePesado','TransitBus','Unknown']) {
  const a=Catalog.resolve({Vehicle_Type:type,Vehicle_PCU:.25}),b=Catalog.resolve({Vehicle_Type:type,Vehicle_PCU:99});
  assert.deepEqual(plain(a.dimensions),plain(b.dimensions),'PCU is never a body scale');
  assert.equal(a.physical.pcu,.25);assert.equal(b.physical.pcu,99);
  assert.equal(a.dimensions.assumed,true);assert.match(a.dimensions.source,/^assumed:/);
}
const explicit={Vehicle_Type:'TransitBus',Vehicle_Dimensions:{length_m:11.2,width_m:2.4,
  source:'effective_vehicle_definition:fixture',provenance:{sha256:'fixture-only'}}};
const effective=Catalog.resolve(explicit);
assert.equal(effective.dimensions.length_m,11.2);assert.equal(effective.dimensions.width_m,2.4);
assert.equal(effective.dimensions.assumed,false);
for(const dimensions of [{length_m:0,width_m:1,source:'bad'},
    {length_m:5,width_m:NaN,source:'bad'},{length_m:5,width_m:1}]) {
  const invalid=Catalog.resolve({Vehicle_Type:'Normal',Vehicle_Dimensions:dimensions});
  assert.equal(invalid.dimensions_origin,'family_assumption');
  assert.equal(invalid.dimension_diagnostics[0].field,'Vehicle_Dimensions');
  assert.deepEqual([invalid.dimensions.length_m,invalid.dimensions.width_m],[4.5,1.8]);
}

const road={num_lanes:1,lane_width_m:3,opposing_lanes:0,offset_eligible:true,native_lanes:{},
  path:[xy(0,0),xy(200,0)],from_node:'a',to_node:'b',allowed_to_links:[]};
const lanes=new Lanes({schema_version:1,links:{road}}),queues=new Queues(lanes);
function marker(spec,i=0,{wait=true,time=50}={}) {
  const start=i,hold=10+i,end=200,distance=200;
  const record={...spec,Replay_Journey_Key:'journey-'+spec.vehicle,Trip:{Trip_ID:spec.Agent_ID+':trip:0001'},
    Link_ID:'road',path:road.path,timestamps:[start,end],Visual_Motion_Fraction:wait ? 1 : .5,Waiting:wait,
    Motion_Plan:{version:1,distance_m:distance,status:'kinematic',
      ...(wait ? {hold_start:hold,native_wait_boundary:hold} : {}),
      phases:wait ? [[start,hold,0,distance/(hold-start),0],[hold,end,distance,0,0]] : [[start,end,0,distance/(end-start),0]]},
    Observed_Waits:wait ? {signal_red:{first:hold,last:end-1,position_evidence:'queue_exit'}} : {}};
  return {...record,...lanes.marker(record,record.Visual_Motion_Fraction,{},xy(100,0))};
}
const roster=fixture.mixed_queue.map((spec,i)=>marker(spec,i)),before=JSON.stringify(roster);
const frame=queues.frame(roster,50);
assert.equal(frame.markers.length,4,'cannot pass by omitting a bus/truck/moto');assert.equal(frame.omitted.length,0);
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,
  length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
for(let i=0;i<frame.markers.length;i++) {
  const current=frame.markers[i],dimensions=fixture.mixed_queue.find(s=>s.vehicle===current.vehicle).expected_dimensions_m;
  assert.deepEqual([current.Visual_Body_Length_Meters,current.Visual_Body_Width_Meters],dimensions);
  assert.equal(current.Visual_Body_Path.length,2,'every body remains rigid');
  assert.equal(current.Visual_Body_Clipped,false);
  near(current.Visual_Safety_Envelope.length_m,dimensions[0]+2);
  near(current.Visual_Safety_Envelope.width_m,dimensions[1]+.2);
  const outline=Picking.bodyOutline(current);
  near(Math.hypot((outline[1][0]-outline[0][0])*scale,(outline[1][1]-outline[0][1])*scale),dimensions[0]);
  near(Math.hypot((outline[2][0]-outline[1][0])*scale,(outline[2][1]-outline[1][1])*scale),dimensions[1]);
  if(i) {
    const prior=frame.markers[i-1];
    const delta=prior.Visual_Queue_Center_Meters-current.Visual_Queue_Center_Meters;
    near(delta,(prior.Visual_Body_Length_Meters+current.Visual_Body_Length_Meters)/2+2);
    assert.equal(queues.envelopesOverlap(body(prior),body(current)),false);
  }
}
assert.equal(JSON.stringify(roster),before,'native intervals, identity, physical PCU and plans stay unchanged');

// Small motorcycles remain selectable without enlarging either body or envelope.
const moto=frame.markers.find(m=>m.vehicle==='moto'),motoBefore=JSON.stringify(moto);
for(const zoom of [1,10,30]) {
  const project=p=>[300+(p[0]-moto.position[0])*scale*zoom,200+(p[1]-moto.position[1])*scale*zoom];
  const options={x:300,y:200+moto.Visual_Body_Width_Meters/2*zoom+4,project,width:1000,height:1000};
  assert.equal(Picking.pick([moto],{...options,radiusPixels:0}),null);
  assert.equal(Picking.pick([moto],options).object,moto);
  assert.equal(Picking.radius('mouse'),8);assert.equal(Picking.radius('touch'),18);
}
assert.equal(JSON.stringify(moto),motoBefore,'selection zoom/aperture never changes metric occupation');

// Representation margins are adjustable; dimensions are not margin settings.
queues.configure({gap_m:3,lateral_clearance_m:.2});
const wider=queues.frame(roster,50);
assert.equal(wider.markers.length,4);
for(const current of wider.markers) {
  near(current.Visual_Safety_Envelope.length_m,current.Visual_Body_Length_Meters+3);
  near(current.Visual_Safety_Envelope.width_m,current.Visual_Body_Width_Meters+.4);
}
assert.throws(()=>queues.configure({car_length_m:20}));
const narrow=new Lanes({schema_version:1,links:{road:{...road,lane_width_m:2.6}}});
const withMargin=new Queues(narrow).frame([roster[0]],50);
assert.equal(withMargin.markers.length,1);assert.equal(withMargin.omitted.length,0);
assert.equal(withMargin.markers[0].Visual_Queue_State,'queued','the body fits even when its safety envelope extends beyond the lane');
assert.equal(withMargin.markers[0].Visual_Body_Width_Meters,2.5);
near(withMargin.markers[0].Visual_Safety_Envelope.width_m,2.7);
const tooNarrow=new Lanes({schema_version:1,links:{road:{...road,lane_width_m:2.4}}});
const noFit=new Queues(tooNarrow).frame([roster[0]],50);
assert.equal(noFit.markers.length,1);assert.equal(noFit.omitted.length,0);
assert.equal(noFit.markers[0].Visual_Queue_State,'body_geometry_unavailable','retain validation when the body itself exceeds the lane');
assert.equal(noFit.markers[0].Visual_Queue_Compatible,false);
assert.equal(noFit.markers[0].Visual_Diagnostic.constraint_violation,true);
assert.equal(noFit.markers[0].Visual_Body_Width_Meters,2.5,'warning must not shrink the bus');

const articulated=marker({vehicle:'articulated',Agent_ID:'p',Vehicle_Type:'TransitBus',Vehicle_Articulated:true},0,{wait:false});
const articulatedBody=lanes.vehicleBody(articulated);
near(articulatedBody.length_m,18);assert.equal(articulatedBody.path.length,2);
assert.equal(Catalog.resolve(articulated).body_model,'rigid_total_envelope_articulation_unknown');
assert.ok(Catalog.resolve(articulated).limitation,'do not claim reconstructed articulated motion');

const cars=[marker({vehicle:'old-normal',Agent_ID:'p1',Profile:'Normal'},0),
  marker({vehicle:'old-liebre',Agent_ID:'p2',Profile:'Liebre'},1)];
const oldFrame=new Queues(lanes).frame(cars,50);
assert.deepEqual(plain(oldFrame.markers.map(m=>m.vehicle)),cars.map(m=>m.vehicle));
assert.ok(oldFrame.markers.every(m=>m.Visual_Vehicle_Presentation.family==='car'),'no new motorcycles or buses');
const untyped=marker({vehicle:'recorded-untyped-vehicle',Agent_ID:'passenger-person',Agent_Type:'TransportePublico'});
const untypedFrame=new Queues(lanes).frame([untyped],50);
assert.equal(untypedFrame.markers.length,1,'a passenger label cannot hide an already recorded vehicle');
assert.equal(untypedFrame.markers[0].vehicle,untyped.vehicle);
assert.equal(untypedFrame.markers[0].Visual_Vehicle_Presentation.family,'passenger');
assert.match(untypedFrame.markers[0].Visual_Vehicle_Presentation.dimensions.source,/:unknown$/);
console.log('PASS: catalog aliases, unknowns, typed rigid bodies, mixed spacing, metric envelopes, small-moto picking and immutable IDs/PCU');
