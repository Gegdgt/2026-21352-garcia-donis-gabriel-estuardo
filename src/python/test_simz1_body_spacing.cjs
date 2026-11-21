'use strict';
// Production loader + controls + geometry, in memory. No browser/HTTP/QSim.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>
  fs.readFileSync('python/'+name,'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]');
const scale=6371008.8*Math.PI/180,xy=(x,y=0)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
const road={path:[xy(0),xy(200)],length_m:200,num_lanes:1,lane_width_m:3.5,opposing_lanes:0,
  offset_eligible:true,from_node:'a',to_node:'b',native_lanes:{},allowed_to_links:[]};
const config={schema_version:1,available:true,links:{road}},lanes=new Lanes(config);
function record(vehicle,Vehicle_Type,start=0,extra={}) {
  const hold=20+start,end=360;
  return {vehicle,Vehicle_Type,Agent_ID:'person:'+vehicle,Replay_Journey_Key:'trip:'+vehicle,
    Link_ID:'road',path:road.path,timestamps:[start,end],...extra,
    Motion_Plan:{version:1,status:'kinematic',distance_m:200,hold_start:hold,native_wait_boundary:hold,
      phases:[[start,hold,0,10,0],[hold,end,200,0,0]]},
    Observed_Waits:{signal_red:{first:hold,last:end-1,position_evidence:'queue_exit'}},
    Visual_Motion_Fraction:1,Waiting:true,Visual_Speed_kmh:0};
}
const placed=raw=>({...raw,...lanes.marker(raw,1,{},road.path[1])});
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,
  length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
for(const [front,rear,expected] of [['Normal','Normal',6.5],['Normal','Motociclista',5.3],['TransitBus','Normal',10.25]]) {
  const q=new Queues(lanes),rows=[placed(record('front',front)),placed(record('rear',rear,1))],source=JSON.stringify(rows);
  const frame=q.frame(rows,30);assert.equal(frame.markers.length,2);assert.equal(frame.omitted.length,0);
  near((frame.markers[0].position[0]-frame.markers[1].position[0])*scale,expected);
  assert.equal(q.envelopesOverlap(...frame.markers.map(body)),false);
  assert.equal(frame.counts.unresolvedOverlaps,0);
  q.configure({gap_m:3});const widened=q.frame(rows,30);
  near((widened.markers[0].position[0]-widened.markers[1].position[0])*scale,expected+1);
  assert.equal(JSON.stringify(rows),source);
}
function configured(length_m,width_m) {
  return {length_m,width_m,source:'synthetic_fixture_VehicleType',nature:'configured',assumed:true,
    measurement_status:'not_established_by_vehicle_type',provenance:{artifact_source:'fixture_only'}};
}
const raw=[record('bus','TransitBus',0,{Vehicle_Physical_Dimensions:configured(13.2,2.45),Vehicle_PCU:2.75}),
  record('car','Normal',1,{Vehicle_Physical_Dimensions:configured(4.8,1.9),Vehicle_PCU:1}),
  record('moto','Motociclista',2,{Vehicle_PCU:.25}),record('truck','TransportePesado',3,{Vehicle_PCU:3.5})];
const originals=JSON.stringify(raw),keys=raw.map(row=>JSON.stringify([row.vehicle,row.Replay_Journey_Key,row.Link_ID,row.timestamps]));
const trips=Object.fromEntries(raw.map(row=>[row.Replay_Journey_Key,{Trip_ID:row.Replay_Journey_Key,
  Person_ID:row.Agent_ID,Departure:row.timestamps[0],Arrival:360,Status:'completed',Origin_Position:xy(0),Destination_Position:xy(200)}]));
const payload={segments:raw,trips,context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]},
  queue_context:{schema_version:1,policy:'native-hold-closure-v1',segments:raw,transition_segments:[],trips,lane_events:[],
    by_seed:Object.fromEntries(keys.map(key=>[key,{complete:true,reason:null,record_keys:keys}]))}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function settled(h) {
  for(let n=0;n<30 && h.api.getState().buffering;n++)await flush();
  assert.equal(h.api.getState().buffering,false);assert.equal(h.api.getState().error,null);h.api.pause();
}
(async()=>{
  const h=harness({},config);h.reply(0,payload);await settled(h);
  try {
    let held=null;
    for(const time of [30,119,120,239,240,250,30]) {
      h.api.seek(time);const index=Math.floor(time/120);
      if(h.request(index))h.reply(index,payload);
      await settled(h);
      const rows=h.api.getVisualDiagnostics(time).records.filter(row=>row.visible);
      assert.equal(rows.length,4);assert.equal(h.count('trips'),4);
      assert.equal(h.api.getVisualDiagnostics(time).counts.unresolvedOverlaps,0);
      const poses=plain(rows.map(r=>[r.vehicle_id,r.position,r.dimensions_m]));
      if(held)assert.deepEqual(poses,held,'mixed bodies keep their spacing through pause, seek and window replacement');
      held=poses;
      near(rows[0].dimensions_m[0],13.2);near(rows[1].dimensions_m[0],4.8);
      near((rows[0].position[0]-rows[1].position[0])*scale,11);
      for(let i=1;i<rows.length;i++) {
        const gap=(rows[i-1].position[0]-rows[i].position[0])*scale-(rows[i-1].dimensions_m[0]+rows[i].dimensions_m[0])/2;
        near(gap,2);near(gap*40,80); // 40 px/m fixture: bodies keep metric size at maximum zoom.
      }
      const contract=h.api.diagnoseVehicle('bus',time).dimension_contract;
      assert.equal(contract.physical_dimensions.nature,'configured');near(contract.physical_dimensions.length_m,13.2);
      assert.equal(contract.visual_body.origin,'recorded_physical');near(contract.safety_envelope.length_m,15.2);
      near(contract.pcu,2.75);assert.equal(contract.picking_tolerance.mouse,8);
      assert.equal(contract.picking_tolerance.changes_metric_body,false);
    }
    assert.equal(JSON.stringify(raw),originals);
    assert.equal(h.requests.filter(r=>r.url.startsWith('/api/journey')).length,0);
  } finally {h.evaluate('continuousReplay.destroy()');}
  const short=new Lanes({schema_version:1,links:{road:{...road,path:[xy(0),xy(8)],length_m:8}}});
  const q=new Queues(short),recorded=raw.map(row=>({...row,path:short.links.get('road').data.path,
    Motion_Plan:{...row.Motion_Plan,distance_m:8,phases:row.Motion_Plan.phases.map((phase,index)=>
      index===0?[phase[0],phase[1],0,.4,0]:[phase[0],phase[1],8,0,0])}}));
  const before=JSON.stringify(recorded),frame=q.frame(recorded.map(row=>({...row,...short.marker(row,1,{},xy(8))})),30);
  assert.equal(frame.markers.length,4);assert.equal(frame.omitted.length,0,'insufficient geometry is not absence');
  assert.ok(frame.counts.incompatiblePosition>0);
  assert.ok(frame.markers.some(m=>m.Visual_Queue_Compatible===false));
  assert.equal(JSON.stringify(recorded),before);
  console.log('PASS: car/car, moto/car, car/bus, registered mixed dimensions, metric gaps, max-zoom scale, pause/seek/three windows, diagnostics and insufficient storage');
})().catch(error=>{console.error(error);process.exitCode=1;});
