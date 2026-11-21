'use strict';
// Renderer equivalence and required-edge controls for indexed causal contexts.
// Synthetic observations only; no native run, SQLite, server or browser IO.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n');
const [Lanes,Queues]=vm.runInNewContext(source+'\n[SimZ1VisualLanes,SimZ1VisualQueues]',{});
const scale=6371008.8*Math.PI/180,xy=(x,y=0)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,epsilon=1e-7)=>assert.ok(Math.abs(a-b)<=epsilon,`${a} != ${b}`);
function road(x0,x1,y,from,to,next=[]) {return {path:[xy(x0,y),xy(x1,y)],num_lanes:1,lane_width_m:3.5,
  opposing_lanes:0,offset_eligible:true,from_node:from,to_node:to,native_lanes:{},allowed_to_links:next,
  movement_source:'effective_car_node_adjacency',osm_tags:{}};}
function setup({gap=.1,lateral=.1,links:givenLinks=null}={}) {
  const links=givenLinks??{a:road(0,100,0,'in','joint',['b']),b:road(100,200,0,'joint','out'),
    adjacent:road(0,100,1,'other-in','other-out'),remote:road(0,100,50,'remote-in','remote-out')};
  const lanes=new Lanes({schema_version:1,available:true,links,occupancy_corridors:{schema:'corridor-length-v1',corridors:
    Object.fromEntries(Object.keys(links).map(k=>[k,{link_ids:[k],represented_lanes:1}]))}});
  return {links,lanes,settings:{gap_m:gap,lateral_clearance_m:lateral},q:new Queues(lanes,{gap_m:gap,lateral_clearance_m:lateral})};
}
function record(f,id,link,start,hold,end,ordinal,{f0=0,f1=1}={}) {
  const length=f.lanes.describe(link).length_m,distance=(f1-f0)*length,stop=hold??end;
  return {vehicle:id,Agent_ID:id,Replay_Journey_Key:'trip:'+id,Link_ID:link,
    Vehicle_Type:'bus',Vehicle_Dimensions:{length_m:12,width_m:2.5,source:'synthetic_fixture',assumed:true},
    path:[f.lanes.place(link,f0*length,0).position,f.lanes.place(link,f1*length,0).position],timestamps:[start,end],
    Native_Occupancy:{policy:'corridor-length-v1',corridor_id:link,model_slot:0,ordinal},
    Boundary_Provenance:{start:'entered link',end:'left link',start_relative:f0,end_relative:f1},
    Motion_Plan:{version:1,status:'kinematic',distance_m:distance,...(hold==null?{}:{hold_start:hold,native_wait_boundary:hold}),
      phases:[[start,stop,0,distance/(stop-start),0],...(hold==null?[]:[[hold,end,distance,0,0]])]},
    Observed_Waits:hold==null?{}:{signal_red:{first:hold,last:end-1,position_evidence:'queue_exit',sources:['MATSim15_QNode_native_branch']}},
    Visual_Queue_Context:{complete:true,role:'resolved_anchor'}};
}
function marker(f,r,t) {
  const fraction=f.q.fractionAt(r,t);
  return {...r,...f.lanes.marker(r,fraction,{},r.path[0]),Visual_Motion_Fraction:fraction,Visual_Distance_m:fraction*r.Motion_Plan.distance_m};
}
function roster(f,rows){return rows.map(r=>marker(f,r,r.Motion_Plan.hold_start??r.timestamps[0]));}
function render(f,active,time,context,neighbors=()=>({}),q=new Queues(f.lanes,f.settings)) {
  return q.frame(active.map(r=>marker(f,r,time)),time,neighbors,context);
}
function signature(frame,id='root') {
  const marker=frame.markers.find(m=>m.vehicle===id),missing=frame.omitted.find(m=>m.vehicle===id);
  assert.ok(marker,'supported root must stay visible: '+missing?.Visual_Queue_State);
  return plain({identity:[marker.vehicle,marker.Replay_Journey_Key,marker.Link_ID,marker.timestamps],position:marker.position,
    center:marker.Visual_Queue_Center_Meters,heading:marker.Visual_Body_Heading_Degrees,
    body:[marker.Visual_Body_Length_Meters,marker.Visual_Body_Width_Meters,marker.Visual_Body_Clipped],
    state:marker.Visual_Queue_State,compatible:marker.Visual_Queue_Compatible,
    turn:marker.Visual_Queue_Turn_Clearance??[],release:marker.Visual_Occupancy_Release_Projection??null,
    native_occupancy:marker.Native_Occupancy,motion:marker.Motion_Plan});
}
const samples=[];
function equivalent(label,f,root,extra,{neighbors=()=>({}),times=[10,10.001,12,40,12,10],kept=[]}={}) {
  const all=[root,...kept,...extra],saved=JSON.stringify(all),full=roster(f,all),causal=roster(f,[root,...kept]);
  const warmFull=new Queues(f.lanes,f.settings),warmCausal=new Queues(f.lanes,f.settings);
  for(const time of times) {
    const a=signature(render(f,[root],time,full,neighbors,warmFull));
    const b=signature(render(f,[root],time,causal,neighbors,warmCausal));
    assert.deepEqual(a,b,label+': equal identity, interval, constraints, body and pose');
    assert.deepEqual(a,signature(render(f,[root],time,[...full].reverse(),neighbors)),label+': cold/reverse order');
    const key=f.q.key(root);
    near(warmFull.anchorCache.base.get(key),warmCausal.anchorCache.base.get(key));
    near(warmFull.anchorCache.final.get(key),warmCausal.anchorCache.final.get(key));
    samples.push({case:label,time,anchor: warmFull.anchorCache.final.get(key),center:a.center});
  }
  assert.equal(JSON.stringify(all),saved,label+': immutable native records');
}

// These exclusions concern historical anchor support. The normal active frame
// continues to contain every active vehicle, including foreign free movements.
for(const margins of [{gap:.1,lateral:.1},{gap:2,lateral:.1},{gap:10,lateral:1}]) {
  const f=setup(margins),root=record(f,'root','a',8,10,50,2);
  equivalent('foreign_moving_without_transfer',f,root,[record(f,'foreign','adjacent',0,null,50,1)]);
  equivalent('foreign_future_hold_without_transfer',f,root,[record(f,'foreign','adjacent',0,20,50,1)]);
  equivalent('foreign_later_render_order',f,root,[record(f,'foreign','adjacent',0,5,50,3)]);
  equivalent('spatially_disjoint_hold',f,root,[record(f,'foreign','remote',0,5,50,1)]);
}

// Earlier cross-group HOLDs are spatial constraints, regardless of whether the
// groups have a common native slot. Removing one changes the root's anchor.
{
  const f=setup(),a=record(f,'root','a',8,10,50,2),b=record(f,'foreign','adjacent',0,5,50,1);
  const fullQ=new Queues(f.lanes,f.settings),missingQ=new Queues(f.lanes,f.settings);
  const full=signature(render(f,[a],12,roster(f,[a,b]),()=>({}),fullQ)),missing=signature(render(f,[a],12,roster(f,[a]),()=>({}),missingQ));
  assert.equal(fullQ.anchorCache.base.get(f.q.key(a)),missingQ.anchorCache.base.get(f.q.key(a)),
    'BASE never reads a different native group, even when its body intersects');
  assert.ok(full.center<missing.center-1,'spatial HOLD dependency must remain');
  samples.push({case:'required_foreign_earlier_hold',full:full.center,missing:missing.center});
}

// Future anchors constrain approach interpolation. Their own future support is
// necessary, even when its start is later than the root's HOLD epoch.
{
  const f=setup(),a=record(f,'root','a',9,10,50,3),b=record(f,'future','a',0,11,50,2),
    c=record(f,'later-predecessor','a',10.1,10.5,50,1);
  const fullQ=new Queues(f.lanes,f.settings),missingQ=new Queues(f.lanes,f.settings);
  const full=signature(render(f,[a],12,roster(f,[a,b,c]),()=>({}),fullQ)),missing=signature(render(f,[a],12,roster(f,[a,b]),()=>({}),missingQ));
  assert.notEqual(fullQ.anchorCache.base.get(f.q.key(b)),missingQ.anchorCache.base.get(f.q.key(b)),
    'a future HOLD still needs its own same-group BASE closure at its future epoch');
  assert.notEqual(full.center,missing.center,'same-group future HOLD support must remain');
  const invalid=roster(f,[a,b,c]);invalid.find(m=>m.vehicle==='future').Visual_Queue_Context.phase='base';
  assert.throws(()=>render(f,[a],12,invalid),/BASE.*FINAL/,'a required FINAL dependency cannot be relabelled BASE');
  samples.push({case:'required_future_same_group',full:full.center,missing:missing.center});
}

// The rear of a body in the next corridor remains an effective predecessor.
// A different current corridor or absent HOLD cannot justify removing it.
for(const futureHold of [null,20]) {
  const f=setup(),a=record(f,'root','a',5.1,6,50,2),prior=record(f,'leader','a',0,null,5,1),
    b=record(f,'leader','b',5,futureHold,50,100);
  const neighbors=m=>m.vehicle==='leader'&&m.Link_ID==='b'?{previous:marker(f,prior,5)}:{};
  const fullQ=new Queues(f.lanes,f.settings),missingQ=new Queues(f.lanes,f.settings);
  const full=signature(render(f,[a],7,roster(f,[a,b]),neighbors,fullQ)),missing=signature(render(f,[a],7,roster(f,[a]),neighbors,missingQ));
  assert.equal(fullQ.anchorCache.base.get(f.q.key(a)),missingQ.anchorCache.base.get(f.q.key(a)),
    'departureBoundary is not consumed by BASE; transferred body remains a FINAL dependency');
  assert.ok(full.center<missing.center,'transferred rear must remain');
  samples.push({case:'required_transferred_rear',futureHold,full:full.center,missing:missing.center});
}

// BASE uses compare(order,key), not ordinal<=. Two equal-ordinal entries in a
// candidate set therefore have a strict direction instead of a reciprocal
// graph edge. Both observations remain present; ambiguity is not erased.
for(const [first,middle,last] of [['alpha','middle','zeta'],['\u{1f697}','\ue000','\uf8ff']]) {
  const f=setup(),a=record(f,middle,'a',8,10,50,2),before=record(f,first,'a',0,5,50,2),
    after=record(f,last,'a',0,5,50,2),key=f.q.key(a);
  assert.ok(f.q.key(before)<key&&key<f.q.key(after),'comparator uses JavaScript UTF-16 order, including astral characters');
  const evaluate=rows=>{const q=new Queues(f.lanes,f.settings);render(f,[],12,roster(f,rows),()=>({}),q);return q.anchorCache.base.get(key);};
  const full=evaluate([after,a,before]),withoutLater=evaluate([a,before]),withoutEarlier=evaluate([a,after]);
  assert.equal(full,withoutLater,'an equal-ordinal later key cannot influence the preceding BASE anchor');
  assert.notEqual(full,withoutEarlier,'an equal-ordinal earlier key remains required');
  samples.push({case:'strict_base_comparator_equal_ordinals',keys:[f.q.key(before),key,f.q.key(after)],full,withoutLater,withoutEarlier});
}

// hold_start alone is not the production eligibility predicate. A nominal
// hold without locating WAIT evidence still follows native FIFO as a movement;
// treating it as a held terminal state would omit its actual predecessor.
{
  const f=setup(),leader=record(f,'leader','a',0,5,50,1),root=record(f,'root','a',1,10,50,2);
  root.Observed_Waits={};assert.equal(f.q.evidence(root,12).eligible,false);
  const evaluate=rows=>{const q=new Queues(f.lanes,f.settings);render(f,[],12,roster(f,rows),()=>({}),q);
    return plain(q.supportState({key:f.q.key(root),role:'fifo',epoch:12,stage:[3,f.q.key(root)]}).result);};
  const full=evaluate([leader,root]),missing=evaluate([root]);
  assert.equal(full.available,true);assert.equal(missing.available,true);assert.ok(full.center_m<missing.center_m);
  samples.push({case:'candidate_hold_is_not_eligible_hold',full:full.center_m,missing:missing.center_m});
}

// Causal dependencies have a role and an epoch: a moving transferred leader
// may itself follow another moving body in its new corridor. That body never
// belonged to the root's corridor, but its FIFO effect is still transitive.
{
  const f=setup(),prior=record(f,'transfer','a',0,5,10,1),transfer=record(f,'transfer','b',10,null,20,100),
    foreign=record(f,'foreign-moving','b',9,null,30,50),forming=record(f,'forming','a',8,15,30,2,{f0:.95}),
    root=record(f,'root','a',9,10,30,3);
  const neighbors=m=>m.vehicle==='transfer'?m.Link_ID==='a'?{next:transfer}:{previous:prior}:{};
  // Direct FINAL departed projection is interpolation, not recursive FIFO.
  // Its predecessor remains necessary when reached through a forming body.
  const directQ=new Queues(f.lanes,f.settings),directMissingQ=new Queues(f.lanes,f.settings);
  const direct=signature(render(f,[root],10,roster(f,[prior,transfer,foreign,root]),neighbors,directQ));
  const directMissing=signature(render(f,[root],10,roster(f,[prior,transfer,root]),neighbors,directMissingQ));
  assert.deepEqual(direct,directMissing,'direct FINAL transferred projection must not acquire foreign recursive FIFO');
  assert.equal(directQ.anchorCache.final.get(f.q.key(root)),directMissingQ.anchorCache.final.get(f.q.key(root)));
  const full=signature(render(f,[root],10,roster(f,[prior,transfer,foreign,forming,root]),neighbors));
  const missing=signature(render(f,[root],10,roster(f,[prior,transfer,forming,root]),neighbors));
  assert.ok(Math.abs(full.center-missing.center)>1,'moving FIFO dependencies must be closed at the queried epoch');
  samples.push({case:'required_transitive_foreign_moving',full:full.center,missing:missing.center,
    direct_final:direct.center,direct_final_without_foreign:directMissing.center});
}

// A scalar transfer certificate cannot replace the complete native chain used
// by departureBoundary. The middle moving rows are needed even without HOLDs.
{
  const f=setup(),a=record(f,'leader','a',0,null,5,1),b1=record(f,'leader','b',5,null,5.5,100,{f1:.01}),
    b2=record(f,'leader','b',5.5,null,6,100,{f0:.01,f1:.02}),b3=record(f,'leader','b',6,null,20,100,{f0:.02}),
    root=record(f,'root','a',6.01,6.1,50,2);
  const chain=[a,b1,b2,b3],neighbors=allowed=>m=>{const i=chain.findIndex(row=>f.q.key(row)===f.q.key(m));
    return i<0?{}:{previous:i&&allowed.includes(chain[i-1])?chain[i-1]:undefined,next:allowed.includes(chain[i+1])?chain[i+1]:undefined};};
  const full=signature(render(f,[root],7,roster(f,[root,b3]),neighbors(chain)));
  const missing=signature(render(f,[root],7,roster(f,[root,b3]),neighbors([b2,b3])));
  assert.notEqual(full.center,missing.center,'native intermediate moving rows must support the indexed transfer');
  samples.push({case:'required_transfer_chain_geometry',full:full.center,missing:missing.center});
}

// The final pass is ordered. A transferred leader with a later ordinal still
// supplies its BASE anchor to an earlier root. Its own final spatial blockers
// must not require a transitive final closure when no requested pose reads it.
{
  const f=setup({links:{a:road(0,100,0,'in','joint',['b']),b:road(100,110,0,'joint','out'),
    foreign:road(110,120,1,'foreign-in','foreign-out')}}),prior=record(f,'leader','a',0,null,5,1),
    leader=record(f,'leader','b',5,20,50,100),blocker=record(f,'later-final-blocker','foreign',0,4,50,50),
    root=record(f,'root','a',5.1,6,50,2);
  const neighbors=m=>m.vehicle==='leader'&&m.Link_ID==='b'?{previous:prior}:{};
  const full=roster(f,[root,leader,blocker]),phased=roster(f,[root,leader]);
  phased.find(m=>m.vehicle==='leader').Visual_Queue_Context={complete:true,role:'resolved_anchor',phase:'base'};
  const fullQ=new Queues(f.lanes,f.settings),phasedQ=new Queues(f.lanes,f.settings);
  for(const time of [6,7,19.99,6]) {
    const expected=signature(render(f,[root],time,full,neighbors,fullQ));
    const actual=signature(render(f,[root],time,phased,neighbors,phasedQ));
    assert.deepEqual(actual,expected,'phase-scoped support must reproduce earlier root exactly');
    near(phasedQ.anchorCache.final.get(f.q.key(leader)),fullQ.anchorCache.base.get(f.q.key(leader)));
  }
  assert.notEqual(fullQ.anchorCache.final.get(f.q.key(leader)),fullQ.anchorCache.base.get(f.q.key(leader)),
    'fixture must contain a real final-only constraint for the transferred leader');
  const baseActive={...leader,Visual_Queue_Context:{complete:true,phase:'base'}};
  const active=signature(render(f,[baseActive],21,phased,neighbors),'leader');
  assert.equal(active.state,'queue_context_incomplete');assert.equal(active.compatible,false,'BASE cannot certify its own active pose');
  const broken=plain(phased);broken.find(m=>m.vehicle==='leader').Visual_Queue_Context.phase='invented';
  assert.throws(()=>render(f,[root],7,broken,neighbors),/Fase de contexto/);
  samples.push({case:'phase_scoped_base_equivalence',root:signature(render(f,[root],7,phased,neighbors)).center,
    leader_base:fullQ.anchorCache.base.get(f.q.key(leader)),leader_final:fullQ.anchorCache.final.get(f.q.key(leader))});
}

// Incomplete source evidence cannot be promoted by sharing a complete roster.
{
  const f=setup(),a=record(f,'root','a',8,10,50,2),saved=roster(f,[a]);
  a.Visual_Queue_Context={complete:false,reason:'fixture_missing_dependency'};
  const result=signature(render(f,[a],12,saved));
  assert.equal(result.state,'queue_context_incomplete');assert.equal(result.compatible,false);
}

// A moving terminal-lane observation with rejected/absent corridor occupancy
// is still an active body. It supplies neither a BASE anchor nor a FINAL HOLD
// constraint, so omitting it from historical anchor context is phase-specific.
// The active marker must remain in the frame and retain its dynamic influence.
{
  const link=road(0,100,0,'in','out');link.length_m=100;
  link.native_lanes={original:{index:null,represented_lanes:1,start_m:100,to_links:[],to_lanes:['terminal']},
    terminal:{index:0,represented_lanes:1,start_m:80,to_links:[],to_lanes:[]}};
  const f=setup({links:{a:link}}),moving=record(f,'moving','a',0,null,20,1),root=record(f,'root','a',1,10,20,2);
  delete moving.Native_Occupancy;delete root.Native_Occupancy;
  const nativeMarker=(row,time)=>{const fraction=f.q.fractionAt(row,time),event={type:'entered lane',vehicle:row.vehicle,
    link:'a',lane:'terminal',time:row.timestamps[0]};return {...row,...f.lanes.marker(row,fraction,
      {lane:'terminal',event,observed_at:time},row.path[0]),Visual_Motion_Fraction:fraction,
      Visual_Distance_m:fraction*row.Motion_Plan.distance_m};};
  const time=9,active=[nativeMarker(moving,time),nativeMarker(root,time)],held=nativeMarker(root,10),
    movingContext=nativeMarker(moving,moving.timestamps[0]);
  assert.equal(f.q.evidence(active[0],time).eligible,false);assert.equal(f.lanes.occupancy(active[0]),null);
  const results=[];
  for(const includeContext of [true,false]){
    const q=new Queues(f.lanes,f.settings),frame=q.frame(active,time,()=>({}),includeContext?[movingContext,held]:[held]);
    assert.ok(frame.markers.some(row=>row.vehicle===moving.vehicle),'moving source body remains visible');
    results.push({signature:signature(frame),base:q.anchorCache.base.get(f.q.key(root)),final:q.anchorCache.final.get(f.q.key(root))});
  }
  assert.deepEqual(results[0],results[1],'pruning only unused anchor context preserves active bodies and follower position');
  const aloneQ=new Queues(f.lanes,f.settings),alone=aloneQ.frame([active[1]],time,()=>({}),[held]);
  assert.equal(aloneQ.anchorCache.base.get(f.q.key(root)),results[0].base);
  assert.equal(aloneQ.anchorCache.final.get(f.q.key(root)),results[0].final);
  assert.notDeepEqual(signature(alone).position,results[0].signature.position,
    'removing the active moving marker would change instantaneous placement and is forbidden');
  const priorHold={...moving,Motion_Plan:{...moving.Motion_Plan,hold_start:5,native_wait_boundary:5,
    phases:[[0,5,0,20,0],[5,20,100,0,0]]},Observed_Waits:{signal_red:{first:5,last:19,
      position_evidence:'queue_exit',sources:['MATSim15_QNode_native_branch']}}},withHoldQ=new Queues(f.lanes,f.settings);
  withHoldQ.frame([],time,()=>({}),[nativeMarker(priorHold,5),held]);
  assert.ok(withHoldQ.anchorCache.base.get(f.q.key(root))<aloneQ.anchorCache.base.get(f.q.key(root)),
    'an eligible native terminal HOLD without corridor occupancy still restricts the same group');
  samples.push({case:'inactive_anchor_context_preserves_active_moving_body',base:results[0].base,final:results[0].final,
    active_with_moving:results[0].signature.position,illegal_active_removal:signature(alone).position,
    required_terminal_hold_base:withHoldQ.anchorCache.base.get(f.q.key(root))});
}
console.log(JSON.stringify({status:'PASS',scope:'synthetic renderer equivalence and required dependencies; no real L12 acceptance',
  cases:25,samples},null,2));
