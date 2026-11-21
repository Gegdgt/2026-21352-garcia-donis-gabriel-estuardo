// Prepared diagnosis reproductions. Explicit user execution only; no browser,
// HTTP, MATSim, population, SQLite, generated replay, or run-file mutation.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict'),crypto=require('node:crypto');
const sources=['simz1_visual_lanes.js','simz1_visual_queues.js','simz1_spatial_view.js'];
const texts=sources.map(name=>fs.readFileSync(path.join(__dirname,name),'utf8'));
const [Lanes,Queues,Spatial]=vm.runInNewContext(texts.join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues,SimZ1SpatialView]',{});
const scale=6371008.8*Math.PI/180,xy=p=>[p[0]/scale,p[1]/scale];
const sha=text=>crypto.createHash('sha256').update(text).digest('hex');
const files=['short-hold','free-crossing','spatial-offset','window-roster'].map(name=>'simz1-visibility-geometry-'+name+'.json');
const evidence=[];
for(const filename of files) {
  const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures',filename),'utf8'));
  const original=JSON.stringify(fixture),links=Object.fromEntries(Object.entries(fixture.links).map(([id,row])=>[id,{
    num_lanes:1,lane_width_m:3,opposing_lanes:0,offset_eligible:true,native_lanes:{},
    movement_source:'effective_car_node_adjacency',source_way:id,osm_tags:{},...row,path:row.path_m.map(xy)}]));
  const lanes=new Lanes({schema_version:1,links}),queues=new Queues(lanes);
  const identity={run_id:fixture.run_id,iteration:fixture.iteration,run_manifest_sha256:'a'.repeat(64)};
  const spatial=fixture.boundary_m ? new Spatial({schema_version:1,mode:'gateway-od',validated:true,identity,
    boundary:{type:'Polygon',coordinates:[fixture.boundary_m.map(xy)]},allowed_links:Object.keys(links)},identity) : null;
  const records=fixture.segments.map(row=>{
    const distance=lanes.describe(row.link_id).length_m,stop=row.hold ?? row.end;
    return {vehicle:row.vehicle_id,Agent_ID:row.person_id,Replay_Journey_Key:row.trip_id,Trip:{Trip_ID:row.trip_id,Person_ID:row.person_id},
      Link_ID:row.link_id,path:links[row.link_id].path,timestamps:[row.start,row.end],
      Motion_Plan:{version:1,status:'kinematic',distance_m:distance,...(row.hold==null ? {} : {hold_start:row.hold,native_wait_boundary:row.hold}),
        phases:[[row.start,stop,0,distance/(stop-row.start),0],...(row.hold==null ? [] : [[stop,row.end,distance,0,0]])]},
      Observed_Waits:row.hold==null ? {} : {signal_red:{first:row.hold,last:row.end,position_evidence:'queue_exit'}}};
  });
  const pose=(record,time)=>{
    const plan=record.Motion_Plan,start=record.timestamps[0],stop=plan.hold_start ?? record.timestamps[1];
    const fraction=Math.max(0,Math.min(1,(time-start)/(stop-start)));
    return {...record,...lanes.marker(record,fraction,{},record.path[0]),Visual_Motion_Fraction:fraction,
      Visual_Native_Center_Position:lanes.place(record.Link_ID,fraction*lanes.describe(record.Link_ID).length_m,null).position,
      Visual_Distance_m:fraction*plan.distance_m,Waiting:plan.hold_start!=null && time>=plan.hold_start};
  };
  const neighbors=marker=>{
    const own=records.find(row=>row.vehicle===marker.vehicle && row.Link_ID===marker.Link_ID && row.timestamps[0]===marker.timestamps[0]);
    const previous=records.find(row=>row.vehicle===own.vehicle && row.timestamps[1]===own.timestamps[0]);
    const next=records.find(row=>row.vehicle===own.vehicle && row.timestamps[0]===own.timestamps[1]);
    return {previous:previous ? pose(previous,previous.timestamps[1]) : null,next:next ? pose(next,next.timestamps[0]) : null};
  };
  const roster=records.filter(row=>row.Motion_Plan.hold_start!=null).map(row=>pose(row,row.Motion_Plan.hold_start));
  for(const probe of fixture.probes) {
    const active=records.filter(row=>row.timestamps[0]<=probe.time && probe.time<row.timestamps[1]);
    const closedRoster=fixture.case_id==='hold_anchor_depends_on_departed_window_roster';
    // The fixture retains both native records. Supply the complete closure for
    // both windows; test_simz1_queue_context.py verifies the indexed SQL recovery.
    // Missing/budget-exceeded context is tested separately through real controls.
    const context=closedRoster ? roster : probe.context_vehicle_ids ? roster.filter(row=>probe.context_vehicle_ids.includes(row.vehicle)) : roster;
    const frame=queues.frame(active.map(row=>pose(row,probe.time)),probe.time,neighbors,context);
    const marker=[...frame.markers,...frame.omitted].find(row=>row.vehicle===probe.vehicle_id);
    assert.ok(marker,'probe must retain the active identity in visible or omitted diagnostics');
    const native=active.find(row=>row.vehicle===probe.vehicle_id),fraction=pose(native,probe.time).Visual_Motion_Fraction;
    const nativePosition=lanes.place(native.Link_ID,fraction*lanes.describe(native.Link_ID).length_m,null).position;
    const inQueue=frame.markers.includes(marker),inSpatial=!spatial || spatial.markers([marker]).length===1;
    const visible=inQueue && inSpatial,reason=!inQueue ? marker.Visual_Queue_State : !inSpatial ? 'spatial_filter' : marker.Visual_Queue_State;
    // JSON preserves the pre-change causal evidence. These current assertions
    // explicitly distinguish the correction from that historical expectation.
    const shortRetained=fixture.case_id==='short_link_wait_omission' && !probe.expected_visible;
    const spatialRetained=fixture.case_id==='lane_offset_leaves_display_polygon' && probe.expected_native_inside===true;
    const expectedVisible=shortRetained || spatialRetained ? true : probe.expected_visible;
    assert.equal(visible,expectedVisible,`${fixture.case_id} at ${probe.time}: current visibility`);
    if(shortRetained) {
      assert.equal(marker.Visual_Queue_Compatible,false);
      assert.equal(marker.Visual_Diagnostic.constraint_violation,true);
      assert.ok(['storage_exceeded','queue_projection_reverses_motion'].includes(marker.Visual_Queue_State));
    } else if(probe.expected_reason && !spatialRetained)assert.equal(reason,probe.expected_reason);
    if(probe.expected_unresolved!=null)assert.equal(frame.counts.unresolvedOverlaps,probe.expected_unresolved);
    // An exact 2 m stop margin moves the former default head forward by .25 m.
    const expectedStation=probe.expected_station_m==null ? null :
      (closedRoster ? fixture.probes[0].expected_station_m : probe.expected_station_m)+.25;
    if(expectedStation!=null)assert.ok(Math.abs(marker.Visual_Queue_Center_Meters-expectedStation)<.001,
      `${fixture.case_id}: expected current station ${expectedStation}, got ${marker.Visual_Queue_Center_Meters}`);
    if(probe.expected_native_inside!=null)assert.equal(spatial.contains(nativePosition),probe.expected_native_inside);
    assert.equal(marker.Visual_Body_Length_Meters,4.5);assert.equal(marker.Visual_Body_Width_Meters,1.8);
    for(const collision of frame.diagnostics.collisions)assert.equal(collision.physical_incompatibility_confirmed,false);
    evidence.push({case_id:fixture.case_id,evidence_kind:'synthetic_reproduction',run_id:fixture.run_id,iteration:fixture.iteration,
      replay_source:fixture.replay_source,client_sources_sha256:Object.fromEntries(sources.map((name,i)=>[name,sha(texts[i])])),
      vehicle_id:marker.vehicle,person_id:marker.Agent_ID,trip_id:marker.Trip.Trip_ID,time:probe.time,
      link_id:marker.Link_ID,lane:marker.Visual_Lane_Index,position:marker.position,native_position:nativePosition,
      dimensions_m:[marker.Visual_Body_Length_Meters,marker.Visual_Body_Width_Meters],visible,reason,
      baseline_expected_visible:probe.expected_visible,baseline_expected_reason:probe.expected_reason ?? null,
      current_constraint_compatible:marker.Visual_Queue_Compatible ?? null,
      display_station_m:marker.Visual_Queue_Center_Meters ?? null,context_vehicle_ids:probe.context_vehicle_ids ?? null,
      current_context_vehicle_ids:context.map(row=>row.vehicle),complete_closure_fixture:closedRoster,
      classification:fixture.classification,details:marker.Visual_Diagnostic ?? null,
      collisions:frame.diagnostics.collisions,forced_qsim_move:'not_evidenced_by_fixture'});
  }
  assert.equal(JSON.stringify(fixture),original,'fixture native timestamps and source records are immutable');
}
if(process.argv.includes('--evidence'))console.log(JSON.stringify(evidence,null,2));
else console.log('PASS: corrected synthetic visibility cases and preserved unresolved crossing; no historical-run attribution');
