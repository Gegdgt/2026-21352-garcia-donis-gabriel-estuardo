'use strict';
// Synthetic native-reservation fixtures exercising the production renderer.
// These metric assertions are not observed centimetric vehicle measurements.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>
  fs.readFileSync('python/'+name,'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]');
const scale=6371008.8*Math.PI/180,xy=(x,y=0)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
const near=(actual,expected,message)=>assert.ok(Math.abs(actual-expected)<1e-5,`${message||''}: ${actual} != ${expected}`);
function road(start,end,from,to,next=[]) {return {path:[xy(start),xy(end)],length_m:end-start,
  num_lanes:1,lane_width_m:3.5,opposing_lanes:0,offset_eligible:true,from_node:from,to_node:to,
  native_lanes:{},allowed_to_links:next,movement_source:'effective_car_node_adjacency'};}
function setup() {
  const links={A:road(0,100,'entry','serial',['B']),B:road(100,106,'serial','crossing',['out']),
    out:road(106,206,'crossing','exit'),cross:{...road(0,100,'side','crossing'),path:[xy(106,-100),xy(106)]}};
  const occupancy_corridors={schema:'corridor-length-v1',corridors:{ab:{link_ids:['A','B'],length_m:106,represented_lanes:1}},
    links:{A:{corridor_id:'ab',offset_m:0,length_m:100},B:{corridor_id:'ab',offset_m:100,length_m:6}}};
  const config={schema_version:1,available:true,links,occupancy_corridors};
  const lanes=new Lanes(config),queues=new Queues(lanes,{gap_m:.1});
  return {config,lanes,queues};
}
const specifications={bus:['TransitBus',12,2.5],truck:['TransportePesado',12,2.5],
  car:['Normal',4.5,1.8],moto:['Motociclista',2.1,.8],tortoise:['Tortuga',4.5,1.8]};
function segment(s,id,family,link,ordinal,start,end,{hold=null,reason='signal_red'}={}) {
  const data=s.config.links[link],[type,length,width]=specifications[family],distance=data.length_m;
  const plan=hold==null ? {version:1,status:'constant',distance_m:distance,phases:[[start,end,0,distance/(end-start),0]]} :
    {version:1,status:'kinematic',distance_m:distance,hold_start:hold,native_wait_boundary:hold,
      phases:[[start,hold,0,distance/(hold-start),0],[hold,end,distance,0,0]]};
  return {vehicle:id,Agent_ID:'person:'+id,Replay_Journey_Key:'journey:'+id,Link_ID:link,
    Vehicle_Type:type,Vehicle_Dimensions:{length_m:length,width_m:width,source:'synthetic_corridor_fixture',assumed:true},
    path:data.path,timestamps:[start,end],Motion_Plan:plan,
    Native_Occupancy:{policy:'corridor-length-v1',corridor_id:'ab',ordinal,model_slot:0},
    Observed_Waits:hold==null?{}:{[reason]:{first:hold,last:end-1,position_evidence:'queue_exit',sources:['synthetic_native_fixture']}}};
}
function marker(s,row,time) {
  const [start,end]=row.timestamps,hold=row.Motion_Plan.hold_start;
  const fraction=Math.max(0,Math.min(1,(time-start)/((hold??end)-start)));
  return {...row,...s.lanes.marker(row,fraction,{},row.path[0]),Visual_Motion_Fraction:fraction,
    Visual_Speed_kmh:hold!=null && time>=hold?0:3.6*row.Motion_Plan.distance_m/((hold??end)-start),Waiting:hold!=null && time>=hold};
}
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,
  length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
const evidence=[];
function verify(s,frame,ids,{stop=false}={}) {
  assert.equal(frame.omitted.length,0,'every native active body remains visible');
  assert.equal(frame.markers.length,ids.length);
  assert.equal(frame.counts.unresolvedOverlaps,0,'no rigid body or safety-envelope overlap');
  const ordered=ids.map(id=>frame.markers.find(m=>m.vehicle===id));
  for(const [i,row] of ordered.entries()) {
    assert.ok(row,'missing native vehicle '+ids[i]);
    assert.equal(row.Visual_Occupancy_Domain,'ab');assert.equal(row.Visual_Occupancy_Reference,'front');
    assert.equal(row.Visual_Occupancy_Position_Observed,false,'front-referenced pose remains an estimate');
    assert.equal(row.Visual_Body_Clipped,false);
    if(stop)assert.ok(row.Visual_Queue_Stop_Clearance_Meters>=-1e-7,'entire body is before intersection conflict plane');
    for(const other of ordered.slice(0,i))assert.equal(s.queues.envelopesOverlap(body(row),body(other)),false,'SAT bodies separated');
    if(i) {
      const leader=ordered[i-1],gap=(leader.position[0]-row.position[0])*scale-
        (leader.Visual_Body_Length_Meters+row.Visual_Body_Length_Meters)/2;
      assert.ok(gap>=.1-1e-7,'longitudinal gap >= 0.10 m: '+gap);
    }
  }
  return ordered;
}
const failures=[];
function test(name,fn) {try{fn();console.log('PASS: '+name);}catch(error){failures.push({name,error});console.error('FAIL: '+name+'\n'+error.stack);}}
for(const family of ['bus','truck'])for(const reason of ['signal_red','storage_wait'])test(family+' stopped across short subdivision '+reason,()=>{
  const s=setup(),raw=[segment(s,'leader',family,'B',1,20,400,{hold:30,reason}),
    segment(s,'car','car','B',2,21,400,{hold:31,reason}),segment(s,'moto','moto','B',3,22,400,{hold:32,reason})];
  const before=JSON.stringify(raw),inputs=raw.map(r=>marker(s,r,40));let baseline;
  for(const time of [40,119.999,120,239.999,240,399,40]) {
    const frame=s.queues.frame(inputs,time),rows=verify(s,frame,['leader','car','moto'],{stop:true});
    const poses=plain(rows.map(m=>[m.vehicle,m.position,m.Visual_Body_Length_Meters]));
    if(baseline)assert.deepEqual(poses,baseline,'frozen FIFO remains fixed across repeated seeks');baseline=poses;
    near(rows[0].Visual_Body_Length_Meters,12);near(rows[1].Visual_Body_Length_Meters,4.5);near(rows[2].Visual_Body_Length_Meters,2.1);
    assert.equal(rows[0].Visual_Queue_Display_Link_ID,'A','12m bus/truck spans the 6m source subdivision');
    evidence.push({case:family+'_'+reason,time,positions:poses,minimum_gap_m:Math.min(...rows.slice(1).map((m,i)=>
      (rows[i].position[0]-m.position[0])*scale-(rows[i].Visual_Body_Length_Meters+m.Visual_Body_Length_Meters)/2)),
      unresolved_overlaps:frame.counts.unresolvedOverlaps,minimum_stop_clearance_m:Math.min(...rows.map(m=>m.Visual_Queue_Stop_Clearance_Meters))});
  }
  assert.equal(JSON.stringify(raw),before);
});
test('blocking facility bus holds car and motorcycle behind its whole body',()=>{
  const s=setup(),stop={start:20,end:100,state:'stop',source:'native_facility_events',link_id:'B',relative_position:1,
    position_source:'MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment',facility_id:'fixture-stop',is_blocking_lane:true};
  const bus={...segment(s,'bus','bus','B',1,20,100),path:[xy(106),xy(106)],
    Boundary_Provenance:{start:'VehicleArrivesAtFacility',end:'VehicleDepartsAtFacility',start_relative:1,end_relative:1},
    Trip:{Transit:{schema:'simz1-transit-replay-v1',vehicle_id:'bus',activity_intervals:[stop]}},Motion_Plan:{status:'stationary',distance_m:0}};
  const raw=[bus,segment(s,'car','car','B',2,21,100,{hold:25}),segment(s,'moto','moto','B',3,22,100,{hold:26})];
  const before=JSON.stringify(raw),rows=verify(s,s.queues.frame(raw.map(r=>marker(s,r,30)),30),['bus','car','moto'],{stop:true});
  assert.equal(rows[0].Boundary_Provenance.start,'VehicleArrivesAtFacility');assert.equal(JSON.stringify(raw),before);
});
test('normal car and motorcycle cannot drive through slower Tortuga',()=>{
  const s=setup(),raw=[segment(s,'slow','tortoise','A',1,0,50),segment(s,'normal','car','A',2,5,25),segment(s,'moto','moto','A',3,6,26)];
  const before=JSON.stringify(raw);
  for(const time of [10,15,20,24])verify(s,s.queues.frame(raw.map(r=>marker(s,r,time)),time),['slow','normal','moto']);
  assert.equal(JSON.stringify(raw),before);
});
test('front reference stays continuous at entry and the 100m/6m internal boundary',()=>{
  const s=setup(),a=segment(s,'bus','bus','A',1,0,100),b=segment(s,'bus','bus','B',1,100,106),source=JSON.stringify([a,b]);
  let previous=null;
  for(const time of [0,.001,1,99.999,100,100.001,102,105.999]) {
    const record=time<100?a:b,neighbors=()=>record===a?{next:b}:{previous:a};
    const row=verify(s,s.queues.frame([marker(s,record,time)],time,neighbors),['bus'])[0];
    const center=row.position[0]*scale;
    near(center,time-6,'front moves one metre per second without link-boundary jump');
    if(previous)assert.ok(center>=previous.center-1e-7,'body never reverses');previous={time,center};
  }
  assert.equal(JSON.stringify([a,b]),source);
});
test('reservation identity mismatch does not manufacture an occupancy corridor',()=>{
  const s=setup(),row=segment(s,'car','car','B',1,20,100,{hold:30});
  assert.ok(s.lanes.occupancy(row));
  for(const invalid of [{corridor_id:'foreign'},{ordinal:-1},{model_slot:4},{policy:'unknown'}])
    assert.equal(s.lanes.occupancy({...row,Native_Occupancy:{...row.Native_Occupancy,...invalid}}),null);
});
function rebuild(s) {s.lanes=new Lanes(s.config);s.queues=new Queues(s.lanes,{gap_m:.1});return s;}
function nativeBus(row) {
  const result={...row,Vehicle_Physical_Dimensions:{length_m:13.5,width_m:2.5,source:'synthetic_registered_VehicleType',
    nature:'configured',measurement_status:'not_established_by_vehicle_type'}};
  delete result.Vehicle_Dimensions;return result;
}
function metricDistance(a,b) {return Math.hypot((a[0]-b[0])*scale,(a[1]-b[1])*scale);}
for(const cosine of [.95,.98])test('13.5m registered bus on curved corridor cos='+cosine,()=>{
  const s=setup(),sine=Math.sqrt(1-cosine*cosine),end=[100+6*cosine,6*sine];
  s.config.links.B.path=[xy(100),xy(...end)];
  s.config.links.out.path=[xy(...end),xy(end[0]+100*cosine,end[1]+100*sine)];
  s.config.links.cross.path=[xy(end[0]+100*sine,end[1]-100*cosine),xy(...end)];rebuild(s);
  const raw=[nativeBus(segment(s,'bus','bus','B',1,20,100,{hold:30})),
    segment(s,'truck','truck','B',2,21,100,{hold:31}),segment(s,'car','car','B',3,22,100,{hold:32})],source=JSON.stringify(raw);
  const frame=s.queues.frame(raw.map(r=>marker(s,r,40)),40),rows=frame.markers;
  assert.equal(frame.omitted.length,0);assert.equal(rows.length,3);assert.equal(frame.counts.unresolvedOverlaps,0);
  for(const [i,row] of rows.entries()) {
    assert.ok(row.Visual_Queue_Stop_Clearance_Meters>=-1e-7,'every body corner remains behind the curved-road stop plane');
    if(i)assert.ok(rows[i-1].Visual_Queue_Center_Meters-row.Visual_Queue_Center_Meters-
      (rows[i-1].Visual_Body_Length_Meters+row.Visual_Body_Length_Meters)/2>=.1-1e-7);
    for(const before of rows.slice(0,i))assert.equal(s.queues.envelopesOverlap(body(row),body(before)),false);
  }
  const bus=rows.find(r=>r.vehicle==='bus');near(bus.Visual_Body_Length_Meters,13.5,'registered dimensions survive domain bounds');
  assert.equal(JSON.stringify(raw),source);
});
test('native modeled slots remain separate in two parallel lanes with opposing traffic',()=>{
  const s=setup(),links=s.config.links;
  for(const id of ['A','B']) {
    const before=links[id];links[id]={...before,num_lanes:2,opposing_lanes:2,reverse_link:id+'r'};
    links[id+'r']={...before,path:[...before.path].reverse(),num_lanes:2,opposing_lanes:2,reverse_link:id,
      from_node:before.to_node,to_node:before.from_node,allowed_to_links:id==='B'?['Ar']:[]};
  }
  s.config.occupancy_corridors.corridors.ab.represented_lanes=2;
  s.config.occupancy_corridors.corridors.ba={link_ids:['Br','Ar'],length_m:106,represented_lanes:2};rebuild(s);
  const raw=[];
  for(const slot of [0,1])for(const reverse of [false,true]) {
    const row=nativeBus(segment(s,(reverse?'reverse-':'forward-')+slot,'bus',reverse?'Ar':'A',slot+1,0,100));
    row.Native_Occupancy={...row.Native_Occupancy,corridor_id:reverse?'ba':'ab',model_slot:slot};raw.push(row);
  }
  const source=JSON.stringify(raw),frame=s.queues.frame(raw.map(r=>marker(s,r,50)),50);
  assert.equal(frame.markers.length,4);assert.equal(frame.omitted.length,0);assert.equal(frame.counts.unresolvedOverlaps,0);
  for(const row of frame.markers) {
    assert.equal(row.Visual_Lane_Index,row.Native_Occupancy.model_slot);
    assert.equal(row.Visual_Lane_Source,'native_modeled_occupancy_slot');near(row.Visual_Body_Length_Meters,13.5);
    const expected=s.lanes.place(row.Visual_Queue_Display_Link_ID,row.Visual_Queue_Display_Station_Meters,row.Native_Occupancy.model_slot);
    near(metricDistance(row.position,expected.position),0,'modeled slot determines the lateral position');
  }
  const forward=frame.markers.filter(r=>r.vehicle.startsWith('forward'));
  near(Math.abs(forward[0].position[1]-forward[1].position[1])*scale,3.5,'independent modeled lanes remain laterally separated');
  assert.equal(JSON.stringify(raw),source);
});
test('native and geometric lengths remain distinct without scaling a registered bus',()=>{
  const s=setup();s.config.links.A.length_m=120;s.config.links.B.length_m=8;
  s.config.occupancy_corridors.corridors.ab.length_m=128;
  s.config.occupancy_corridors.links.A.length_m=120;
  Object.assign(s.config.occupancy_corridors.links.B,{offset_m:120,length_m:8});rebuild(s);
  const a=nativeBus(segment(s,'bus','bus','A',1,0,100)),b=nativeBus(segment(s,'bus','bus','B',1,100,108)),original=JSON.stringify([s.config,a,b]);
  let before;
  for(const time of [99.999999,100]) {
    const row=time<100?a:b,adjacent=()=>time<100?{next:b}:{previous:a};
    const frame=s.queues.frame([marker(s,row,time)],time,adjacent),shown=frame.markers[0];
    assert.equal(frame.omitted.length,0);near(shown.Visual_Body_Length_Meters,13.5);near(shown.position[0]*scale,93.25,'geometry endpoint front minus half body');
    if(before)assert.ok(metricDistance(before.position,shown.position)<.00001);before=shown;
  }
  assert.equal(JSON.stringify([s.config,a,b]),original);
});
test('native reservation cannot select a slot outside represented corridor lanes',()=>{
  const s=setup();s.config.links.A.num_lanes=2;s.config.links.B.num_lanes=2;rebuild(s);
  const row=segment(s,'bus','bus','A',1,0,100);row.Native_Occupancy.model_slot=1;
  assert.equal(s.config.occupancy_corridors.corridors.ab.represented_lanes,1);
  assert.ok(s.lanes.occupancy(row)===null,'two geometric lanes do not authorize an unreserved model slot');
});
test('hold to next corridor cannot silently jump a 13.5m bus across the stop setback',()=>{
  const s=setup();s.config.occupancy_corridors.corridors.after={link_ids:['out'],length_m:100,represented_lanes:1};rebuild(s);
  const before=nativeBus(segment(s,'bus','bus','B',1,20,100,{hold:30})),after=nativeBus(segment(s,'bus','bus','out',1,100,200));
  after.Native_Occupancy.corridor_id='after';
  const pre=s.queues.frame([marker(s,before,99.999999)],99.999999,()=>({next:after})).markers[0];
  const post=s.queues.frame([marker(s,after,100)],100,()=>({previous:before})).markers[0];
  const displacement=metricDistance(pre.position,post.position);
  evidence.push({case:'hold_next_corridor_transition',time_before:99.999999,time_after:100,
    displacement_m:displacement,before:plain(pre),after:plain(post)});
  assert.ok(displacement<.001,'body jumps '+displacement+' m in one microsecond at native release');
});
test('8m passage prefix and 100m reserved receipt preserve a 13.5m bus transition',()=>{
  const s=setup();s.config.links.P=road(-8,0,'before','entry',['A']);
  s.config.occupancy_corridors.corridors.ab={link_ids:['A'],length_m:100,represented_lanes:1};
  s.config.occupancy_corridors.links={A:{corridor_id:'ab',offset_m:0,length_m:100}};rebuild(s);
  const prefix=nativeBus(segment(s,'bus','bus','P',1,0,8)),receipt=nativeBus(segment(s,'bus','bus','A',1,8,108));
  for(const row of [prefix,receipt])Object.assign(row.Native_Occupancy,{passage_links:['P'],passage_slots:[0],receipt_link:'A'});
  const source=JSON.stringify([prefix,receipt]);let prior;
  for(const time of [0,7,7.999999,8,8.000001,10]) {
    const row=time<8?prefix:receipt,frame=s.queues.frame([marker(s,row,time)],time,()=>time<8?{next:receipt}:{previous:prefix});
    assert.equal(frame.markers.length,1);assert.equal(frame.omitted.length,0);const shown=frame.markers[0];
    near(shown.position[0]*scale,time-8-6.75,'front progresses across backed passage/receipt');
    near(shown.Visual_Body_Length_Meters,13.5);assert.equal(shown.Visual_Occupancy_Domain,'ab');
    if(prior&&time-prior.time<.00001)assert.ok(metricDistance(prior.position,shown.position)<.0001);
    prior={time,position:shown.position};
  }
  assert.equal(JSON.stringify([prefix,receipt]),source);
});
test('curved short-link exit preserves the backed multi-link rear and heading',()=>{
  const s=setup(),cosine=.95,sine=Math.sqrt(1-cosine*cosine),end=[100+6*cosine,6*sine];
  s.config.links.B.path=[xy(100),xy(...end)];
  s.config.links.out.path=[xy(...end),xy(end[0]+100*cosine,end[1]+100*sine)];
  s.config.links.cross.path=[xy(end[0]+100*sine,end[1]-100*cosine),xy(...end)];
  s.config.occupancy_corridors.corridors.after={link_ids:['out'],length_m:100,represented_lanes:1};rebuild(s);
  const before=nativeBus(segment(s,'bus','bus','B',1,100,106)),after=nativeBus(segment(s,'bus','bus','out',1,106,206));
  after.Native_Occupancy.corridor_id='after';
  const pre=s.queues.frame([marker(s,before,105.999999)],105.999999,()=>({next:after})).markers[0];
  const post=s.queues.frame([marker(s,after,106)],106,()=>({previous:before})).markers[0];
  const displacement=metricDistance(pre.position,post.position),headingChange=Math.abs(((post.Visual_Body_Heading_Degrees-pre.Visual_Body_Heading_Degrees+540)%360)-180);
  evidence.push({case:'curved_short_exit',time_before:105.999999,time_after:106,displacement_m:displacement,heading_change_degrees:headingChange,
    before:plain(pre),after:plain(post)});
  assert.ok(displacement<.001,'rear jumps '+displacement+' m because only the 6m predecessor was considered');
  assert.ok(headingChange<.001,'body heading jumps '+headingChange+' degrees at a continuous native boundary');
});
test('partial link approach, internal facility dwell and release preserve the same bus front',()=>{
  const s=setup();s.config.links.A.native_lanes={original:{index:0,represented_lanes:1,start_m:100,to_lanes:['terminal']},
    terminal:{index:0,represented_lanes:1,start_m:75,to_lanes:[]}};rebuild(s);
  const stop={start:25,end:50,state:'stop',source:'native_facility_events',link_id:'A',relative_position:.25,
    position_source:'native_lane_membership_and_verified_lane_endpoint',lane_id:'original',facility_id:'internal-quarter',is_blocking_lane:true};
  const trip={Transit:{schema:'simz1-transit-replay-v1',vehicle_id:'bus',activity_intervals:[stop]}};
  function partial(start,end,from,to,startEvent,endEvent) {
    return {...nativeBus(segment(s,'bus','bus','A',1,start,end)),Trip:trip,path:[xy(from*100),xy(to*100)],
      Boundary_Provenance:{start:startEvent,end:endEvent,start_relative:from,end_relative:to,distance:'network_length_fraction'},
      Motion_Plan:{version:1,status:from===to?'stationary':'constant',distance_m:(to-from)*100,
        phases:from===to?[]:[[start,end,0,(to-from)*100/(end-start),0]]}};
  }
  const approach=partial(0,25,0,.25,'entered link','VehicleArrivesAtFacility'),
    dwell=partial(25,50,.25,.25,'VehicleArrivesAtFacility','VehicleDepartsAtFacility'),
    release=partial(50,125,.25,1,'VehicleDepartsAtFacility','left link');
  const native=JSON.stringify([approach,dwell,release]),jumps=[];let previous;
  for(const time of [0,24.999999,25,49.999999,50,50.000001,124.999999]) {
    const record=time<25?approach:time<50?dwell:release,neighbors=()=>record===approach?{next:dwell}:record===dwell?{previous:approach,next:release}:{previous:dwell};
    const frame=s.queues.frame([marker(s,record,time)],time,neighbors),shown=frame.markers[0];
    assert.equal(frame.omitted.length,0);assert.equal(frame.markers.length,1);assert.equal(shown.Visual_Lane_Source,'native_modeled_occupancy_slot');
    near(shown.Visual_Body_Length_Meters,13.5);
    if(previous&&time-previous.time<.00001) {
      const displacement=metricDistance(previous.position,shown.position);
      evidence.push({case:'internal_facility_boundary',time_before:previous.time,time_after:time,displacement_m:displacement});
      if(displacement>=.001)jumps.push({time,displacement_m:displacement});
    }
    previous={time,position:shown.position};
  }
  assert.equal(JSON.stringify([approach,dwell,release]),native);
  assert.ok(jumps.length===0,'internal facility body jumps: '+JSON.stringify(jumps));
});
test('terminal blocking facility keeps approach dwell and release behind the same conflict boundary',()=>{
  const s=setup();s.config.occupancy_corridors.corridors.after={link_ids:['out'],length_m:100,represented_lanes:1};rebuild(s);
  const stop={start:26,end:51,state:'stop',source:'native_facility_events',link_id:'B',relative_position:1,
    position_source:'MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment',facility_id:'terminal-stop',is_blocking_lane:true};
  const trip={Transit:{schema:'simz1-transit-replay-v1',vehicle_id:'bus',activity_intervals:[stop]}};
  function partial(start,end,from,to,startEvent,endEvent) {
    return {...nativeBus(segment(s,'bus','bus','B',1,start,end)),Trip:trip,path:[xy(100+from*6),xy(100+to*6)],
      Boundary_Provenance:{start:startEvent,end:endEvent,start_relative:from,end_relative:to,distance:'network_length_fraction'},
      Motion_Plan:{version:1,status:from===to?'stationary':'constant',distance_m:(to-from)*6,
        phases:from===to?[]:[[start,end,0,(to-from)*6/(end-start),0]]}};
  }
  const approach=partial(20,26,0,1,'entered link','VehicleArrivesAtFacility'),
    dwell=partial(26,51,1,1,'VehicleArrivesAtFacility','VehicleDepartsAtFacility'),
    release=partial(51,52,1,1,'VehicleDepartsAtFacility','left link'),
    next=nativeBus(segment(s,'bus','bus','out',1,52,152));
  next.Native_Occupancy.corridor_id='after';
  const source=JSON.stringify([approach,dwell,release,next]),jumps=[];let previous;
  for(const time of [20,25.999999,26,50.999999,51,51.000001,51.999999,52,52.000001]) {
    const record=time<26?approach:time<51?dwell:time<52?release:next,
      neighbors=()=>record===approach?{next:dwell}:record===dwell?{previous:approach,next:release}:record===release?{previous:dwell,next}:{previous:release};
    const frame=s.queues.frame([marker(s,record,time)],time,neighbors),shown=frame.markers[0];
    assert.equal(frame.omitted.length,0);assert.equal(frame.markers.length,1);near(shown.Visual_Body_Length_Meters,13.5);
    if(record===dwell) {
      assert.ok(shown.Visual_Queue_Stop_Clearance_Meters>=-1e-7);
      assert.ok(shown.Visual_Queue_Stop_Boundary.geometric_setback_m>0,'fixture has a real geometry-derived conflict margin');
    }
    if(previous&&time-previous.time<.00001) {
      const displacement=metricDistance(previous.marker.position,shown.position);
      evidence.push({case:'terminal_facility_boundary',time_before:previous.time,time_after:time,displacement_m:displacement,
        before:plain(previous.marker),after:plain(shown)});
      if(displacement>=.001)jumps.push({time,displacement_m:displacement});
    }
    previous={time,marker:shown};
  }
  assert.equal(JSON.stringify([approach,dwell,release,next]),source);
  assert.ok(jumps.length===0,'terminal facility body jumps: '+JSON.stringify(jumps));
});
test('two buses retain separate FIFO bodies across simultaneous facility departure and arrival',()=>{
  const s=setup();s.config.occupancy_corridors.corridors.after={link_ids:['out'],length_m:100,represented_lanes:1};rebuild(s);
  const rows=[];
  for(const [id,ordinal,arrive,depart,exit] of [['first',1,26,51,57],['second',2,51,76,77]]) {
    const stop={start:arrive,end:depart,state:'stop',source:'native_facility_events',link_id:'B',relative_position:1,
      position_source:'MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment',facility_id:'terminal-stop',is_blocking_lane:true};
    const trip={Transit:{schema:'simz1-transit-replay-v1',vehicle_id:id,activity_intervals:[stop]}};
    for(const [start,end,startEvent,endEvent] of [[arrive,depart,'VehicleArrivesAtFacility','VehicleDepartsAtFacility'],
      [depart,exit,'VehicleDepartsAtFacility','left link']]) {
      const row={...nativeBus(segment(s,id,'bus','B',ordinal,start,end)),Trip:trip,path:[xy(106),xy(106)],
        Boundary_Provenance:{start:startEvent,end:endEvent,start_relative:1,end_relative:1,distance:'network_length_fraction'},
        Motion_Plan:{version:1,status:'stationary',distance_m:0,phases:[[start,end,0,0,0]]}};
      if(id==='first' && start===depart) {
        row.Motion_Plan.native_wait_boundary=depart+1;
        row.Observed_Waits={storage_wait:{first:depart+1,last:exit-1,position_evidence:'queue_exit',sources:['synthetic_native_fixture']}};
      }
      rows.push(row);
    }
    const next={...nativeBus(segment(s,id,'bus','out',ordinal,exit,exit+100)),Trip:trip};
    next.Native_Occupancy.corridor_id='after';rows.push(next);
  }
  const neighbor=row=>{
    const own=rows.filter(r=>r.vehicle===row.vehicle),i=own.findIndex(r=>r.timestamps[0]===row.timestamps[0]);
    return {previous:own[i-1],next:own[i+1]};
  };
  const before=JSON.stringify(rows),snapshots=[];
  for(const time of [51,56.999999,57,75.999999,76,76.999999,77,51]) {
    const active=rows.filter(r=>r.timestamps[0]<=time && time<r.timestamps[1]).map(r=>marker(s,r,time));
    const context=rows.filter(r=>r.Motion_Plan.status==='stationary').map(r=>marker(s,r,r.timestamps[0]));
    const frame=s.queues.frame(active,time,neighbor,context);
    assert.equal(frame.omitted.length,0);assert.equal(frame.markers.length,2);
    assert.equal(frame.counts.unresolvedOverlaps,0,'native post-dwell interval retains the earlier bus body');
    const second=frame.markers.find(r=>r.vehicle==='second');
    snapshots.push({time,position:second.position,center:second.Visual_Queue_Center_Meters});
  }
  for(const [left,right] of [[75.999999,76],[76.999999,77]])
    assert.ok(metricDistance(snapshots.find(r=>r.time===left).position,snapshots.find(r=>r.time===right).position)<.001,
      'follower may not jump to stop endpoint when service ends');
  assert.equal(JSON.stringify(rows),before,'native data are not rewritten');
  evidence.push({case:'simultaneous_facility_handoff',samples:snapshots});
});
test('passage can enter an internal 100m receipt without resetting the corridor offset',()=>{
  const s=setup();s.config.links.B=road(100,200,'serial','crossing',['out']);
  s.config.links.out=road(200,300,'crossing','exit');s.config.links.cross.path=[xy(200,-100),xy(200)];
  s.config.links.P=road(92,100,'branch','serial',['B']);
  s.config.occupancy_corridors.corridors.ab.length_m=200;s.config.occupancy_corridors.links.B.length_m=100;rebuild(s);
  const prefix=nativeBus(segment(s,'bus','bus','P',1,0,8)),receipt=nativeBus(segment(s,'bus','bus','B',1,8,108));
  for(const row of [prefix,receipt])Object.assign(row.Native_Occupancy,{passage_links:['P'],passage_slots:[0],receipt_link:'B'});
  const before=JSON.stringify([s.config,prefix,receipt]);let previous;
  for(const time of [0,7.999999,8,8.000001,50]) {
    const row=time<8?prefix:receipt,frame=s.queues.frame([marker(s,row,time)],time,()=>time<8?{next:receipt}:{previous:prefix});
    assert.equal(frame.omitted.length,0);assert.equal(frame.markers.length,1);const shown=frame.markers[0];
    near(shown.position[0]*scale,92+time-6.75,'receipt uses its native position within the original corridor');
    assert.equal(shown.Visual_Occupancy_Domain,'ab');assert.equal(shown.Native_Occupancy.receipt_link,'B');
    if(previous&&time-previous.time<.00001)assert.ok(metricDistance(previous.position,shown.position)<.0001);
    previous={time,position:shown.position};
  }
  assert.equal(JSON.stringify([s.config,prefix,receipt]),before);
});
for(const lengths of [[8],[3,4]])test('boundary exit keeps original reservation through '+lengths.join('+')+'m connectors',()=>{
  const s=setup(),exitLinks=[];let from=106,node='crossing';
  for(const [i,length] of lengths.entries()) {
    const id='X'+i,next='outside'+i;exitLinks.push(id);
    s.config.links[id]=road(from,from+length,node,next,i+1<lengths.length?['X'+(i+1)]:[]);from+=length;node=next;
  }
  s.config.links.B.allowed_to_links=[exitLinks[0]];rebuild(s);
  const origin=nativeBus(segment(s,'bus','bus','B',1,100,106)),records=[origin];let time=106;
  for(const [i,id] of exitLinks.entries()) {
    const row=nativeBus(segment(s,'bus','bus',id,1,time,time+lengths[i]));time+=lengths[i];
    Object.assign(row.Native_Occupancy,{exit_links:exitLinks,exit_slots:exitLinks.map(()=>0),exit_from_link:'B',passage_kind:'boundary_exit'});
    records.push(row);
  }
  const original=JSON.stringify([s.config,records]),times=[105.999999,106,106.000001,
    ...records.slice(1,-1).flatMap(row=>[row.timestamps[1]-.000001,row.timestamps[1],row.timestamps[1]+.000001]),time-.000001];
  let previous;
  for(const t of times) {
    const i=records.findIndex(r=>r.timestamps[0]<=t&&t<r.timestamps[1]),row=records[i];
    const frame=s.queues.frame([marker(s,row,t)],t,()=>({previous:records[i-1],next:records[i+1]}));
    assert.equal(frame.markers.length,1);assert.equal(frame.omitted.length,0);const shown=frame.markers[0];
    near(shown.position[0]*scale,t-6.75,'exit geometry is continuous until native traffic exit');
    near(shown.Visual_Body_Length_Meters,13.5);assert.equal(shown.Visual_Occupancy_Domain,'ab');
    assert.equal(shown.Native_Occupancy.corridor_id,'ab');assert.equal(shown.Native_Occupancy.ordinal,1);
    const occupancy=s.lanes.occupancy(row);near(occupancy.corridor.data.length_m,106,'native quota length is not enlarged by the exit suffix');
    if(previous&&t-previous.time<.00001)assert.ok(metricDistance(previous.position,shown.position)<.0001);
    previous={time:t,position:shown.position};
  }
  assert.equal(s.queues.frame([],time).markers.length,0,'no parked vehicle is invented beyond native EXIT');
  assert.equal(JSON.stringify([s.config,records]),original);
  const exit=records[1];
  for(const invalid of [{exit_from_link:'A'},{passage_kind:'unknown'},{exit_slots:[9]},{exit_links:['foreign']}])
    assert.ok(s.lanes.occupancy({...exit,Native_Occupancy:{...exit.Native_Occupancy,...invalid}})===null,'unbacked exit passage is not accepted');
});
test('waiting exit suffix does not relabel extended geometry as extra native storage',()=>{
  const s=setup();s.config.links.X=road(106,114,'crossing','exit');s.config.links.B.allowed_to_links=['X'];rebuild(s);
  const row=nativeBus(segment(s,'bus','bus','X',1,106,140,{hold:114}));
  Object.assign(row.Native_Occupancy,{exit_links:['X'],exit_slots:[0],exit_from_link:'B',passage_kind:'boundary_exit'});
  const frame=s.queues.frame([marker(s,row,120)],120),shown=frame.markers[0];
  assert.equal(frame.omitted.length,0);assert.equal(shown.Visual_Occupancy_Domain,'ab');
  assert.ok(shown.Visual_Queue_Storage_Source!=='native_corridor_length_reservation'||Math.abs(shown.Visual_Queue_Storage_Meters-106)<1e-7,
    'native storage is 106m; drawn exit path must not advertise '+shown.Visual_Queue_Storage_Meters+'m as native capacity');
});
test('release from a held origin into its exit suffix preserves the front despite unchanged reservation identity',()=>{
  const s=setup();s.config.links.X=road(106,114,'crossing','exit');s.config.links.B.allowed_to_links=['X'];rebuild(s);
  const origin=nativeBus(segment(s,'bus','bus','B',1,20,100,{hold:30})),exit=nativeBus(segment(s,'bus','bus','X',1,100,108));
  Object.assign(exit.Native_Occupancy,{exit_links:['X'],exit_slots:[0],exit_from_link:'B',passage_kind:'boundary_exit'});
  const before=s.queues.frame([marker(s,origin,99.999999)],99.999999,()=>({next:exit})).markers[0];
  const after=s.queues.frame([marker(s,exit,100)],100,()=>({previous:origin})).markers[0];
  const displacement=metricDistance(before.position,after.position);
  evidence.push({case:'held_origin_boundary_exit',time_before:99.999999,time_after:100,displacement_m:displacement,
    before:plain(before),after:plain(after)});
  assert.ok(displacement<.001,'held origin to boundary exit jumps '+displacement+' m');
  assert.equal(after.Native_Occupancy.corridor_id,origin.Native_Occupancy.corridor_id);
});
test('exit from an internal origin link trims unused downstream geometry while retaining native quota',()=>{
  const s=setup(),cosine=.95,sine=Math.sqrt(1-cosine*cosine);
  s.config.links.B=road(100,200,'serial','crossing',['out']);
  s.config.links.out=road(200,300,'crossing','exit');s.config.links.cross.path=[xy(200,-100),xy(200)];
  s.config.links.X={...road(100,108,'serial','branchExit'),path:[xy(100),xy(100+8*cosine,8*sine)]};
  s.config.links.A.allowed_to_links=['B','X'];
  s.config.occupancy_corridors.corridors.ab.length_m=200;s.config.occupancy_corridors.links.B.length_m=100;rebuild(s);
  const origin=nativeBus(segment(s,'bus','bus','A',1,0,100)),exit=nativeBus(segment(s,'bus','bus','X',1,100,108));
  Object.assign(exit.Native_Occupancy,{exit_links:['X'],exit_slots:[0],exit_from_link:'A',passage_kind:'boundary_exit'});
  const source=JSON.stringify([s.config,origin,exit]);let previous;
  for(const time of [99.999999,100,100.000001,107,107.999999]) {
    const row=time<100?origin:exit,occupancy=s.lanes.occupancy(row);
    assert.ok(occupancy,'native exit from an internal source member remains accepted');
    near(occupancy.corridor.data.length_m,200,'original quota remains intact');
    if(row===exit) {
      assert.deepEqual(plain(occupancy.corridor.parts.map(p=>p.link.id)),['A','X'],'unused member B is not an exit trajectory');
      near(occupancy.corridor.length,108,'only travelled prefix and exit connector supply geometry');
    }
    const frame=s.queues.frame([marker(s,row,time)],time,()=>time<100?{next:exit}:{previous:origin});
    assert.equal(frame.omitted.length,0);assert.equal(frame.markers.length,1);const shown=frame.markers[0];
    // A rigid body spanning the bend has its centre off the polyline. Test its
    // recorded front and geometric rear, rather than requiring the old centre
    // heuristic which could put that rear into an unrelated approach.
    const front=time<=100 ? xy(time) : xy(100+(time-100)*cosine,(time-100)*sine);
    const frontX=time<=100 ? time : 100+(time-100)*cosine,frontY=time<=100 ? 0 : (time-100)*sine;
    const rearX=frontX-Math.sqrt(13.5*13.5-frontY*frontY),rear=xy(rearX),expected=xy((frontX+rearX)/2,frontY/2);
    assert.ok(metricDistance(shown.Visual_Body_Path[1],front)<1e-5,'native front follows the actual recorded exit');
    assert.ok(metricDistance(shown.Visual_Body_Path[0],rear)<1e-5,'full rigid rear stays on the travelled origin');
    assert.ok(metricDistance(shown.position,expected)<1e-5,'centre is the midpoint of the supported front and rear');
    assert.ok(shown.Visual_Body_Reconstruction.source_parts.every(part=>part.link_id!=='B'),
      'unused reserved member never supplies body geometry');
    assert.notEqual(shown.Visual_Queue_Display_Link_ID,'B');near(shown.Visual_Body_Length_Meters,13.5);
    if(previous&&time-previous.time<.00001)assert.ok(metricDistance(previous.position,shown.position)<.0001);
    previous={time,position:shown.position};
  }
  assert.equal(JSON.stringify([s.config,origin,exit]),source);
});
test('sequential bus car motorcycle release preserves historical follower anchors and rear occupancy',()=>{
  const s=setup();s.config.occupancy_corridors.corridors.after={link_ids:['out'],length_m:100,represented_lanes:1};rebuild(s);
  const families=['bus','car','moto'],departures=[100,108,110],records=[];
  for(let index=0;index<families.length;index++) {
    const family=families[index],before=segment(s,family,family,'B',index+1,20+index,departures[index],{hold:30+index});
    const after=segment(s,family,family,'out',index+1,departures[index],departures[index]+20);
    after.Native_Occupancy.corridor_id='after';records.push(before,after);
  }
  const original=JSON.stringify(records),context=records.map(row=>marker(s,row,row.Motion_Plan.hold_start??row.timestamps[0]));
  const neighbors=row=>{
    const pair=records.filter(record=>record.vehicle===row.vehicle),index=pair.findIndex(record=>record.Link_ID===row.Link_ID);
    return {previous:pair[index-1],next:pair[index+1]};
  };
  const times=[40,99.999999,100,100.000001,103,107.999999,108,108.000001,109.999999,110,110.000001,115];
  const samples=[];let previous;
  for(const time of times) {
    const active=records.filter(row=>row.timestamps[0]<=time&&time<row.timestamps[1]);
    const frame=s.queues.frame(active.map(row=>marker(s,row,time)),time,neighbors,context);
    const bodies=families.map(id=>frame.markers.find(row=>row.vehicle===id));
    assert.equal(frame.markers.length,3,'all native active vehicles stay visible');assert.equal(frame.omitted.length,0);
    const gaps=bodies.slice(1).map((row,index)=>(bodies[index].position[0]-row.position[0])*scale-
      (bodies[index].Visual_Body_Length_Meters+row.Visual_Body_Length_Meters)/2);
    const displacements=previous&&time-previous.time<.00001?bodies.map((row,index)=>metricDistance(previous.bodies[index].position,row.position)):[];
    samples.push({time,centers_m:bodies.map(row=>row.position[0]*scale),gaps_m:gaps,displacements_m:displacements,
      unresolved_overlaps:frame.counts.unresolvedOverlaps,markers:plain(bodies)});
    previous={time,bodies};
  }
  evidence.push({case:'sequential_queue_release',samples});
  assert.equal(JSON.stringify(records),original,'native motion plans, waits, timestamps and reservation IDs remain immutable');
  for(const sample of samples) {
    assert.equal(sample.unresolved_overlaps,0,'body/envelope overlap at '+sample.time);
    for(const gap of sample.gaps_m)assert.ok(gap>=.1-1e-7,'gap at '+sample.time+' is '+gap);
    for(const [index,displacement] of sample.displacements_m.entries())assert.ok(displacement<.001,
      families[index]+' jumps '+displacement+' m at '+sample.time+' after its historical anchor');
  }
  assert.ok(samples.find(row=>row.time===100).centers_m[0]-6<106,'bus rear remains in origin immediately after native link entry');
});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function settled(h) {for(let n=0;n<30&&h.api.getState().buffering;n++)await flush();assert.equal(h.api.getState().buffering,false);assert.equal(h.api.getState().error,null);h.api.pause();}
(async()=>{
  const s=setup(),raw=[segment(s,'bus','bus','B',1,20,400,{hold:30}),segment(s,'truck','truck','B',2,21,400,{hold:31}),
    segment(s,'car','car','B',3,22,400,{hold:32}),segment(s,'moto','moto','B',4,23,400,{hold:33})];
  const original=JSON.stringify(raw),keys=raw.map(r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key,r.Link_ID,r.timestamps]));
  const trips=Object.fromEntries(raw.map(r=>[r.Replay_Journey_Key,{Trip_ID:r.Replay_Journey_Key,Person_ID:r.Agent_ID,
    Departure:r.timestamps[0],Arrival:400,Status:'completed',Origin_Position:xy(0),Destination_Position:xy(106)}]));
  const payload={segments:raw,trips,context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]},
    queue_context:{schema_version:1,policy:'native-hold-closure-v1',segments:raw,transition_segments:[],trips,lane_events:[],
      by_seed:Object.fromEntries(keys.map(key=>[key,{complete:true,reason:null,record_keys:keys}]))}};
  const h=harness({},s.config);
  try {
    h.reply(0,payload);await settled(h);h.api.setQueueGap(.1);let previous=null;
    for(const time of [40,119,120,239,240,350,40]) {
      h.api.seek(time);if(h.request(Math.floor(time/120)))h.reply(Math.floor(time/120),payload);await settled(h);
      const d=h.api.getVisualDiagnostics(time),rows=d.records.filter(r=>r.visible);
      assert.equal(rows.length,4);assert.equal(h.count('trips'),4);assert.equal(d.counts.unresolvedOverlaps,0);
      const poses=plain(rows.map(r=>[r.vehicle_id,r.position,r.dimensions_m]));
      if(previous)assert.deepEqual(poses,previous,'continuous replay preserves shared-corridor queue through cache/window changes');previous=poses;
      assert.ok(rows.every(r=>r.stop_clearance_m>=-1e-7));
      for(let i=1;i<rows.length;i++)assert.ok((rows[i-1].position[0]-rows[i].position[0])*scale-(rows[i-1].dimensions_m[0]+rows[i].dimensions_m[0])/2>=.1-1e-7);
    }
    assert.equal(JSON.stringify(raw),original);console.log('PASS: continuous shared corridor, all four families, three windows and reverse seek');
  }catch(error){failures.push({name:'continuous shared corridor',error});console.error(error.stack);}
  finally{h.evaluate('continuousReplay.destroy()');}
  const releaseSetup=setup();releaseSetup.config.occupancy_corridors.corridors.after={link_ids:['out'],length_m:100,represented_lanes:1};rebuild(releaseSetup);
  const releaseRows=['bus','car','moto'].flatMap((family,index)=>{
    const departure=[100,108,110][index],before=segment(releaseSetup,family,family,'B',index+1,20+index,departure,{hold:30+index});
    const after=segment(releaseSetup,family,family,'out',index+1,departure,departure+20);after.Native_Occupancy.corridor_id='after';return [before,after];
  });
  const held=releaseRows.filter(row=>row.Link_ID==='B'),heldKeys=held.map(row=>JSON.stringify([row.vehicle,row.Replay_Journey_Key,row.Link_ID,row.timestamps]));
  const releaseTrips=Object.fromEntries(releaseRows.map(row=>[row.Replay_Journey_Key,{Trip_ID:row.Replay_Journey_Key,Person_ID:row.Agent_ID,
    Departure:20,Arrival:130,Status:'completed',Origin_Position:xy(0),Destination_Position:xy(206)}]));
  const releasePayload=index=>({segments:releaseRows.filter(row=>row.timestamps[0]<(index+1)*120&&row.timestamps[1]>index*120),
    trips:releaseTrips,context_segments:index===1?held.filter(row=>row.vehicle!=='bus'):[],lane_replay:{events:[]},signal_replay:{series:[]},
    queue_context:{schema_version:1,policy:'native-hold-closure-v1',segments:held,transition_segments:releaseRows.filter(row=>row.Link_ID==='out'),
      trips:releaseTrips,lane_events:[],by_seed:Object.fromEntries(heldKeys.map(key=>[key,{complete:true,reason:null,record_keys:heldKeys}]))}});
  const releaseOriginal=JSON.stringify(releaseRows),releaseHarnesses=[];
  try {
    const poses=[];
    for(const cold of [false,true]) {
      const replay=harness({},releaseSetup.config);releaseHarnesses.push(replay);
      replay.reply(0,cold?{...releasePayload(0),segments:[],context_segments:[],queue_context:{...releasePayload(0).queue_context,segments:[],transition_segments:[],by_seed:{}}}:releasePayload(0));
      await settled(replay);replay.api.setQueueGap(.1);
      if(!cold){replay.api.seek(109);await settled(replay);}
      for(const time of cold?[120,125]:[119.999999,120,125,120]) {
        replay.api.seek(time);const index=Math.floor(time/120);if(replay.request(index))replay.reply(index,releasePayload(index));await settled(replay);
        const diagnostics=replay.api.getVisualDiagnostics(time),visible=diagnostics.records.filter(row=>row.visible);
        assert.equal(diagnostics.counts.unresolvedOverlaps,0,'released queue remains separated across windows');
        const pair=visible.filter(row=>['car','moto'].includes(row.vehicle_id)).sort((a,b)=>a.vehicle_id.localeCompare(b.vehicle_id));
        assert.equal(pair.length,2);const snapshot=plain(pair.map(row=>[row.vehicle_id,row.position,row.dimensions_m]));
        poses.push({cold,time,poses:snapshot});
      }
    }
    for(const time of [120,125]) {
      const matching=poses.filter(row=>row.time===time);
      for(const row of matching.slice(1))assert.deepEqual(row.poses,matching[0].poses,'historical release anchor survives cold seek/window/cache at '+time);
    }
    const before=poses.find(row=>row.time===119.999999),after=poses.find(row=>row.time===120);
    for(let index=0;index<2;index++)assert.ok(metricDistance(before.poses[index][1],after.poses[index][1])<.001,'no window-boundary jump after a released HOLD');
    assert.equal(JSON.stringify(releaseRows),releaseOriginal);
    evidence.push({case:'continuous_sequential_release_windows',samples:poses});
    console.log('PASS: continuous sequential release retains departed leader context across cold and reverse window seeks');
  }catch(error){failures.push({name:'continuous sequential release windows',error});console.error(error.stack);}
  finally{for(const replay of releaseHarnesses)replay.evaluate('continuousReplay.destroy()');}
  fs.mkdirSync('runtime/validation',{recursive:true});
  fs.writeFileSync('runtime/validation/corridor-occupancy-fixtures.json',JSON.stringify({scope:'synthetic native reservation metadata; metric production-renderer assertions',
    status:failures.length?'failed':'passed',failures:failures.map(f=>({name:f.name,error:f.error.message})),cases:evidence},null,2));
  if(failures.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
