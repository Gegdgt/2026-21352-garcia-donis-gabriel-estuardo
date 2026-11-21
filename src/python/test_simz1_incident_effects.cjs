// Pure module + production controls/loader in VM. No browser, server or QSim.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync('python/simz1_incident_effects.js','utf8'),context);
const Effects=vm.runInContext('SimZ1IncidentEffects',context),json=x=>JSON.parse(JSON.stringify(x));
const identity={run_id:'validated-real-draw',iteration:0,run_manifest_sha256:'b'.repeat(64)};
function record(changes={}) {
  return {incident_id:'fixture-incident',opportunity_id:'analytic-fixture',link_id:'road',lane:'road.lane.0',
    vehicles:['a','b'],participants:['a','b'].map(vehicle_id=>({vehicle_id,person_id:null,vehicle_type:'car',link_id:'road',lane:'road.lane.0'})),
    start_seconds:100,scheduled_end_seconds:1900,end_seconds:1900,censored_seconds:null,status:'resolved',duration_seconds:1800,
    physics_effect:'none',intended_physics_effect:'independent_lane_hold',evidence_ref:'analytic-fixture:two-recorded-participants',
    provenance:{scope:'fixture_only',adapter_version:'uninstalled',adapter_evidence:'fixture_gate_only_not_native'},...changes};
}
function envelope(records=[record()],changes={}) {
  return {schema:'simz1-lane-incident-replay-v1',scope:'fixture_only',adapter_installed:false,
    adapter_version:'uninstalled',adapter_evidence:'fixture_gate_only_not_native',identity,horizon_seconds:2400,records,diagnostics:[],...changes};
}
function fixture(payload=envelope()) {const e=new Effects({identity,allowFixture:true});e.replace(payload,identity);return e;}
function marker(vehicle,changes={}) {
  return {vehicle,Link_ID:'road',Observed_Queue_ID:'road.lane.0',position:[0,0],color:[255,255,255],
    Visual_Body_Path:[[0,0],[1,0]],Visual_Body_Length_Meters:4.5,Visual_Body_Width_Meters:1.8,
    Motion_Plan:{status:'stationary'},Visual_Speed_kmh:0,timestamps:[0,2200],...changes};
}
{
  const e=new Effects({identity}),rows=[marker('a'),marker('b')];
  e.replace(envelope(),identity);const frame=e.frame(rows,100);
  assert.equal(e.snapshot(100).status,'adapter_not_installed');assert.equal(e.snapshot(100).rejected_records,1);
  assert.strictEqual(frame.markers,rows);assert.equal(frame.icons.length,0);
  e.replace(envelope(undefined,{scope:'native',adapter_installed:true,adapter_version:'claimed'}),identity);
  assert.equal(e.snapshot(100).status,'adapter_not_installed','sidefile cannot install adapter');
  e.replace(null,identity);assert.equal(e.snapshot(100).status,'disabled_no_incident_records');
  const f=fixture(envelope(undefined,{scope:'native',adapter_installed:true}));
  assert.equal(f.rows.length,0,'even isolated fixture option cannot accept native claims');
}
{
  const e=fixture(),rows=[marker('a'),marker('b'),marker('c')],before=JSON.stringify(rows);
  for(const t of [99.999,1900,2200])assert.strictEqual(e.frame(rows,t).markers,rows,'half-open lifetime '+t);
  for(const t of [100,1899.999,101,100]) {
    const f=e.frame(rows,t);assert.equal(f.markers.length,3);assert.equal(f.participant_count,2);assert.equal(f.icons.length,1);
    for(let i=0;i<2;i++) {
      assert.deepEqual(json(f.markers[i].color),[255,140,0]);
      for(const key of ['position','Visual_Body_Path','Motion_Plan','timestamps'])assert.strictEqual(f.markers[i][key],rows[i][key]);
      for(const key of ['Visual_Body_Length_Meters','Visual_Body_Width_Meters','Visual_Speed_kmh'])assert.equal(f.markers[i][key],rows[i][key]);
    }
    assert.strictEqual(f.markers[2],rows[2]);assert.strictEqual(e.frame(rows,t).markers[0],f.markers[0],'reuse decorated immutable marker');
    assert.equal(f.icons[0].position_source,'participant_visual_pose;not_native_incident_location');
  }
  assert.equal(JSON.stringify(rows),before,'never tint the cached source marker');
  assert.equal(e.frame([],100).icons.length,0,'missing participants are not invented');
  assert.equal(e.frame([marker('a',{Link_ID:'other'}),marker('b',{Observed_Queue_ID:'road.lane.1'})],100).participant_count,0);
  assert.equal(e.frame([marker('a',{Observed_Queue_ID:null})],100).participant_count,0,'unknown lane cannot match');
  assert.equal(e.frame([marker('a')],100).markers.length,1,'absent second participant never creates a body');
}
{
  const row=record({status:'censored',end_seconds:null,censored_seconds:200}),e=fixture(envelope([row],{horizon_seconds:200}));
  assert.equal(e.active(199.999).length,1);assert.equal(e.active(200).length,1,'retain last observed censored image');
  assert.equal(e.active(200.000001).length,0,'no extrapolation past replay horizon');
  assert.equal(e.participant(marker('a'),199).censored,true);assert.equal(e.rows[0].end_seconds,null,'censorship is not recovery');
  assert.equal(e.rows[0].scheduled_end_seconds,1900);
}
{
  for(const bad of [record({status:'active',end_seconds:null}),record({duration_seconds:1799}),
    record({end_seconds:1899}),record({physics_effect:'independent_lane_hold'}),record({vehicles:['a','a']}),
    {type:'zona1IncidentStart',link:'road',start:100}, {type:'simz1IncidentStartDesign'}, {type:'FORCE'}]) {
    const e=fixture(envelope([bad]));assert.equal(e.rows.length,0);assert.equal(e.frame([marker('a')],100).participant_count,0);
  }
  for(const change of [{run_id:'another'},{iteration:1}])assert.equal(fixture(envelope(undefined,{identity:{...identity,...change}})).rows.length,0);
  const e=fixture(envelope([record(),record()]));assert.equal(e.rows.length,1,'deduplicate immutable repeated window records');
  e.replace(envelope([record(),record({evidence_ref:'contradictory'})]),identity);assert.equal(e.rows.length,0);
  assert.equal(e.snapshot(100).reasons.conflicting_incident_id,1);
  e.replace(envelope([record(),record({duration_seconds:1799})]),identity);assert.equal(e.rows.length,0,'malformed duplicate invalidates its ID');
  e.replace(envelope([record(),record({incident_id:'other',opportunity_id:'another'})]),identity);
  assert.equal(e.rows.length,0,'overlapping exact lane/participants rejected');
  assert.equal(e.snapshot(100).reasons.overlapping_lane_or_participant_incidents,2);
  e.replace(envelope([record(),record({incident_id:'next',start_seconds:1900,scheduled_end_seconds:3700,end_seconds:3700})],
    {horizon_seconds:4000}),identity);assert.equal(e.rows.length,0,'one opportunity cannot produce another incident');
  assert.equal(e.snapshot(1900).reasons.repeated_opportunity_id,2);
  const missingType=record();delete missingType.participants[0].vehicle_type;
  assert.equal(fixture(envelope([missingType])).rows.length,0,'participant types are mandatory evidence');
  assert.equal(fixture(envelope([record({start_seconds:0.000001,scheduled_end_seconds:1800.000001,end_seconds:1800.000001})])).rows.length,1);
  assert.equal(fixture(envelope([record({start_seconds:0.0000001,scheduled_end_seconds:1800.0000001,end_seconds:1800.0000001})])).rows.length,0);
}
{
  class IconLayer {constructor(props){this.props=props;}}
  const a=Effects.layer({IconLayer}),b=Effects.layer({IconLayer});
  assert.equal(a.props.id,'synthetic-incident-emergency');assert.equal(a.props.pickable,false);
  assert.equal(a.props.iconAtlas,b.props.iconAtlas);assert.equal(a.props.sizeUnits,'pixels');
  assert.equal(a.props.getPosition({position:[3,4]})[0],3);assert.equal(a.props.data.length,0);
  const rows=Array.from({length:300},(_,i)=>record({incident_id:'i'+i,opportunity_id:'opportunity'+i,link_id:'road'+i,lane:'road'+i+'.lane.0',vehicles:['a'+i,'b'+i],
    participants:['a'+i,'b'+i].map(vehicle_id=>({vehicle_id,vehicle_type:'car',link_id:'road'+i,lane:'road'+i+'.lane.0'}))}));
  const f=fixture(envelope(rows)).frame(rows.flatMap(r=>r.vehicles.map(id=>marker(id,{Link_ID:r.link_id,Observed_Queue_ID:r.lane}))),100);
  assert.equal(f.icons.length,300);assert.equal(f.markers.length,600,'one batch preserves hundreds of bodies');
}

const {harness,segment,key}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function payload(synthetic=envelope()) {
  const rows=['a','b','c'].map((id,i)=>({...segment('road',0,2200,i*10,i*10),vehicle:id,Agent_ID:'person-'+id,
    Motion_Plan:{version:1,status:'stationary',distance_m:0,cap_mps:12,phases:[[0,2200,0,0,0]]}}));
  return {segments:rows,trips:{[key]:{Trip_ID:'fixture',Departure:0,Arrival:2200,Status:'completed'}},
    lane_replay:{events:rows.map(row=>({vehicle:row.vehicle,link:'road',lane:'road.lane.0',time:0,type:'entered lane'}))},
    synthetic_incidents:synthetic};
}
const options={end_seconds:2400,window_count:20,source_time_horizon:{start_seconds:0,end_seconds:2400}};
const colors=h=>json(h.evaluate("layers.find(l=>l.id==='trips').props.data.map(row=>row.color)"));
(async()=>{
  {
    const scale=6371008.8*Math.PI/180,path=[[0,0],[2200/scale,0]],data=payload();
    for(const row of data.segments){row.path=path;row.Vehicle_Type='Normal';}
    const lanes={schema_version:1,available:true,lane_width_m:3.5,links:{road:{path,length_m:2200,num_lanes:1,
      opposing_lanes:0,offset_eligible:true,from_node:'a',to_node:'b',allowed_to_links:[],
      native_lanes:{'road.lane.0':{index:0,start_m:2200,to_links:[],represented_lanes:1}}}}};
    const off=harness(options,lanes),on=harness(options,lanes,null,undefined,{incidentFixture:true});
    for(const h of [off,on]){h.reply(0,data);await flush();h.api.pause();h.api.seek(100);}
    const bodies=h=>json(h.evaluate("layers.find(l=>l.id==='trips').props.data.map(r=>[r.vehicle,r.position,r.Visual_Body_Path,r.Visual_Body_Length_Meters,r.Visual_Body_Width_Meters,r.Motion_Plan,r.Visual_Speed_kmh])"));
    assert.equal(bodies(on).length,3);assert.equal(bodies(on)[0][2].length,2);assert.equal(bodies(on)[0][3],4.5);
    assert.deepEqual(bodies(on),bodies(off),'real lane/queue result is unchanged by incident decoration');
    assert.deepEqual(json(on.api.getVisualDiagnostics().counts),json(off.api.getVisualDiagnostics().counts));
    assert.deepEqual(colors(on),[[255,140,0],[255,140,0],[255,255,255]]);
    assert.deepEqual(colors(off),Array(3).fill([255,255,255]));
    for(const h of [off,on])h.evaluate('continuousReplay.destroy()');
  }
  {
    const h=harness({...options,allowFixture:true,incidentFixture:true});
    h.reply(0,{...payload(),incidents:[{Link_ID:'road',start:0,end:2200,position:[0,0]}]});await flush();
    h.api.pause();h.api.seek(100);
    assert.deepEqual(colors(h),Array(3).fill([255,255,255]));assert.equal(h.count('synthetic-incident-emergency'),0);
    assert.equal(h.count('incidents'),1,'legacy generic incident remains separate');
    const d=h.api.getVisualDiagnostics();assert.equal(d.synthetic_incidents.adapter_installed,false);
    assert.equal(d.synthetic_incidents.rejected_records,1);assert.equal(d.synthetic_incidents.status,'adapter_not_installed');
    h.evaluate('continuousReplay.destroy()');
  }
  {
    const h=harness(options,null,null,undefined,{incidentFixture:true});h.reply(0,payload());await flush();h.api.pause();
    const white=Array(3).fill([255,255,255]),orange=[[255,140,0],[255,140,0],[255,255,255]];
    h.api.seek(99.999);assert.deepEqual(colors(h),white);
    h.api.seek(100);assert.deepEqual(colors(h),orange);assert.equal(h.count('synthetic-incident-emergency'),1);
    assert.equal(h.api.diagnoseVehicle('a').synthetic_incident.incident_id,'fixture-incident');
    assert.equal(h.api.getState().visibleMarkers,3);
    const geometry=h.evaluate("JSON.stringify(layers.find(l=>l.id==='trips').props.data.map(r=>[r.position,r.Motion_Plan,r.Visual_Speed_kmh]))");
    h.api.seek(99);assert.deepEqual(colors(h),white);
    h.api.seek(130);h.reply(1,payload());await flush();assert.deepEqual(colors(h),orange,'carry-in state after atomic window activation');
    h.api.seek(1899);h.reply(15,payload());await flush();assert.deepEqual(colors(h),orange);
    h.api.seek(1900);assert.deepEqual(colors(h),white);assert.equal(h.count('synthetic-incident-emergency'),0);
    assert.equal(h.evaluate("JSON.stringify(layers.find(l=>l.id==='trips').props.data.map(r=>[r.position,r.Motion_Plan,r.Visual_Speed_kmh]))"),geometry);
    h.api.seek(100);await flush();assert.deepEqual(colors(h),orange,'cached reverse seek reconstructs by absolute time');
    h.sandbox.incidentReplacement=h.payload(0,payload(null));
    h.evaluate('SimZ1ContinuousLoader.validateRecords(incidentReplacement,config.continuous,0,0,120);replaceContinuousWindow(incidentReplacement);render()');
    assert.deepEqual(colors(h),white,'same paused clock replacement clears decoration');
    assert.equal(h.count('synthetic-incident-emergency'),0);assert.equal(h.api.getState().visibleMarkers,3);
    h.sandbox.incidentReplacement=h.payload(0,payload());
    h.evaluate('SimZ1ContinuousLoader.validateRecords(incidentReplacement,config.continuous,0,0,120);replaceContinuousWindow(incidentReplacement);render()');
    assert.deepEqual(colors(h),orange,'same paused clock replacement activates accepted fixture');
    assert.equal(h.evaluate("JSON.stringify(layers.find(l=>l.id==='trips').props.data.map(r=>[r.position,r.Motion_Plan,r.Visual_Speed_kmh]))"),geometry);
    h.evaluate('continuousReplay.destroy()');
  }
  console.log('SimZ1 incident effects: module + fixture UI contracts PASS (production disabled)');
})().catch(error=>{console.error(error);process.exitCode=1;});
