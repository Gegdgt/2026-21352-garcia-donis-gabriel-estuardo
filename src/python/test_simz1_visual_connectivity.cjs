// Prepared read-only fixture. Execute explicitly; no browser, server or run IO.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const VisualLanes=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VisualLanes;');
const {inspect}=require('./inspect_simz1_visual_connectivity.cjs');
const clone=value=>JSON.parse(JSON.stringify(value));
// Topology and native lane destinations: run simz1-0dd152dabbc24d1d84d9b738c449cc35,
// iteration 0, output_network SHA256 33c4dcbf7da9cd1f3e2df1cbbdff597802a5a4dce31472c15a6acb4fdcf512f3,
// output_lanes SHA256 114e0e2da087b578961674455eb2305f3724a293dfe7a37edc3b834e22ee449e.
// Coordinates below are source OSM nodes (local approximate map, not surveyed GIS).
const nodes={
  '412160765':[-90.5057265,14.626343], '412162813':[-90.5053771,14.626297],
  '3133825094':[-90.5056404,14.6243363], '412162906':[-90.5050097,14.6262476],
  '412162909':[-90.5048883,14.627204], '412162910':[-90.5045034,14.6271625],
  '412162814':[-90.5052115,14.6271613]};
const fixtures=[
  {incoming:'osm_1059594347_0_backward',outgoing:'osm_35137582_0_forward',
    from:'412160765',via:'412162813',to:'3133825094',opposing:[1,0],
    names:['22 Calle','19 Avenida']},
  {incoming:'osm_35137583_6_forward',outgoing:'osm_35137628_1_forward',
    from:'412162906',via:'412162909',to:'412162910',opposing:[0,1],
    names:['20 Avenida','21 Calle']},
  {incoming:'osm_375611743_16_forward',outgoing:'osm_400885349_0_forward',
    from:'412162906',via:'412162813',to:'412162814',opposing:[0,1],
    names:['22 Calle','19 Avenida']}];
function data(fixture) {
  const {incoming:a,outgoing:b,from,via,to,opposing,names}=fixture;
  const make=(id,start,end,index)=>({from_node:start,to_node:end,path:[nodes[start],nodes[end]],
    num_lanes:1,opposing_lanes:opposing[index],reverse_link:opposing[index] ? id+'-source-reverse' : null,
    source_way:id.split('_')[1],lane_width_m:3,offset_eligible:true,osm_tags:{name:names[index]},
    movement_source:'effective_lane_definitions',native_lanes:{}});
  const links={[a]:make(a,from,via,0),[b]:make(b,via,to,1)};
  links[a].native_lanes[a+'.lane.0']={index:0,represented_lanes:1,to_links:[b]};
  return links;
}
function setup(links) {return new VisualLanes({schema_version:1,links});}
function distance(a,b) {
  const scale=6371008.8*Math.PI/180;
  return Math.hypot((a[0]-b[0])*scale*Math.cos((a[1]+b[1])*.5*Math.PI/180),(a[1]-b[1])*scale);
}
for(const fixture of fixtures) {
  const links=data(fixture),before=JSON.stringify(links),renderer=setup(links),connectors=renderer.connectors();
  assert.equal(connectors.length,1,fixture.names.join(' -> '));
  const curve=connectors[0];
  assert.equal(curve.Link_ID,fixture.incoming);assert.equal(curve.To_Link_ID,fixture.outgoing);
  assert.equal(curve.source,'permitted_single_lane_turn_schematic');
  assert.equal(curve.setback_source,'inferred_visual_only');assert.equal(curve.setback_m,3.5);
  assert.equal(curve.path.length,13);assert.ok(curve.path.flat().every(Number.isFinite));
  assert.equal(renderer.snapshot().inferredSingleLaneTurnConnectors,1);
  assert.equal(renderer.snapshot().reversingConnectorsOmitted,0);
  const audit=inspect({visual_lanes:{schema_version:1,available:true,links},
    focus_link_ids:[fixture.incoming,fixture.outgoing]});
  assert.equal(audit.read_only,true);assert.equal(audit.spatial_clipping_active,false);
  assert.equal(audit.summary.focused_links,2);
  assert.equal(audit.summary.focused_unrepresented_nonreversing_movements,0);
  assert.equal(audit.movements.length,1);
  assert.equal(audit.movements[0].via_node,fixture.via);
  assert.equal(audit.movements[0].classification,'visual_connector_present');
  assert.equal(audit.movements[0].connectors,1);assert.equal(audit.movements[0].visible_connectors,1);
  assert.deepEqual(audit.movements[0].inset_setbacks_m,[3.5]);
  assert.ok(audit.movements[0].minimum_offset_endpoint_gap_m>0);
  const identity={run_id:'visual-connectivity-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64)};
  const clipped=inspect({visual_lanes:{schema_version:1,available:true,links,identity},
    focus_link_ids:[fixture.incoming,fixture.outgoing],spatial_demand:{schema_version:1,mode:'gateway-od',
      validated:true,identity,allowed_links:[fixture.incoming],boundary:{type:'Polygon',coordinates:[[
        [-90.51,14.62],[-90.50,14.62],[-90.50,14.63],[-90.51,14.63],[-90.51,14.62]]]}}});
  assert.equal(clipped.spatial_clipping_active,true);
  assert.equal(clipped.movements[0].connectors,1);
  assert.equal(clipped.movements[0].visible_connectors,0,'visual domain filtering is separate from native connectivity');
  assert.equal(clipped.links.find(row=>row.id===fixture.outgoing).visible_pieces,0);
  const a=renderer.links.get(fixture.incoming),b=renderer.links.get(fixture.outgoing);
  const expectedStart=renderer.sample(a.geometry,1-3.5/a.geometry.length,renderer.offset(a,0)).position;
  const expectedEnd=renderer.sample(b.geometry,3.5/b.geometry.length,renderer.offset(b,0)).position;
  assert.ok(distance(curve.path[0],expectedStart)<1e-6);
  assert.ok(distance(curve.path.at(-1),expectedEnd)<1e-6);
  const withoutMovement=clone(links);withoutMovement[fixture.incoming].native_lanes={};
  const unchanged=setup(withoutMovement);
  assert.deepEqual(clone(renderer.roads()),clone(unchanged.roads()),'road geometry is unchanged');
  for(const id of [fixture.incoming,fixture.outgoing]) {
    // body(link ID, longitudinal metres, lane index, length metres, width metres)
    const renderedBody=renderer.body(id,10,0,4.5,1.8),originalBody=unchanged.body(id,10,0,4.5,1.8);
    assert.ok(renderedBody && originalBody,'fixture must compare actual bodies, never null fallbacks');
    assert.equal(renderedBody.length_m,4.5);assert.equal(renderedBody.width_m,1.8);
    assert.deepEqual(clone(renderedBody),clone(originalBody),
      'schematic connectors never participate in rigid vehicle placement');
  }
  assert.equal(JSON.stringify(links),before,'native lane destinations, nodes and source geometry stay immutable');
  const privateAccess=clone(links);
  privateAccess[fixture.outgoing].osm_tags.access='private';
  privateAccess[fixture.incoming].native_lanes[fixture.incoming+'.lane.0'].to_links=[];
  const privateRenderer=setup(privateAccess);
  assert.ok(privateRenderer.roads().some(row=>row.Link_ID===fixture.outgoing),'private road can remain visible context');
  assert.equal(privateRenderer.connectors().length,0,
    'a private access excluded by effective lane permissions stays disconnected despite shared node and geometry');
  for(const alter of [
    d=>{d[fixture.incoming].native_lanes[fixture.incoming+'.lane.0'].to_links=[];},
    d=>{d[fixture.outgoing].from_node='separate-node-at-identical-coordinates';},
    d=>{d[fixture.outgoing].osm_tags={bridge:'yes',layer:'1'};},
    d=>{d[fixture.outgoing].osm_tags={tunnel:'yes',layer:'-1'};},
    d=>{d[fixture.outgoing].num_lanes=2;},
    d=>{d[fixture.outgoing].to_node=fixture.from;},
    d=>{d[fixture.outgoing].path.reverse();}
  ]) {
    const changed=clone(links);alter(changed);
    assert.equal(setup(changed).connectors().length,0,'no inferred permission, target lane, level crossing or U-turn');
  }
  const short=clone(links),start=short[fixture.incoming].path[0],end=short[fixture.incoming].path[1];
  short[fixture.incoming].path[0]=end.map((value,i)=>value+(start[i]-value)*.001);
  const shortRenderer=setup(short);
  assert.equal(shortRenderer.connectors().length,0,'insufficient terminal length is reported, not invented');
  assert.equal(shortRenderer.snapshot().reversingConnectorsOmitted,1);
  assert.ok(shortRenderer.snapshot().issues.some(row=>row.reason==='reversing_visual_connector_without_supported_curve'));
  const unresolved=inspect({visual_lanes:{schema_version:1,available:true,links:short},
    focus_link_ids:[fixture.incoming]});
  assert.equal(unresolved.summary.focused_unrepresented_nonreversing_movements,1,
    'the read-only inspector must expose an unsupported drawing without connecting it');
  assert.throws(()=>inspect({visual_lanes:{schema_version:1,available:true,links},
    focus_link_ids:[fixture.incoming,fixture.incoming]}),/unique/);
}
// A rejected miter does not by itself prove that the rendered road disappears:
// short inner-turn centre endpoints can differ while their metric strips overlap.
function shortSameWay(lengthDegrees) {
  const common={num_lanes:1,opposing_lanes:1,reverse_link:'fixture-reverse',source_way:'fixture-service',
    lane_width_m:3,offset_eligible:true,osm_tags:{highway:'service'},movement_source:'effective_lane_definitions'};
  const links={a:{...common,from_node:'before',to_node:'joint',path:[[-90-lengthDegrees,14],[-90,14]],
    native_lanes:{'a.lane.0':{index:0,represented_lanes:1,to_links:['b']}}},
    b:{...common,from_node:'joint',to_node:'after',path:[[-90,14],[-90,14-lengthDegrees]],native_lanes:{}}};
  return inspect({visual_lanes:{schema_version:1,available:true,links},focus_link_ids:['a','b']});
}
const overlappingShort=shortSameWay(.00001);
assert.equal(overlappingShort.global_geometry_issues.length,1);
assert.equal(overlappingShort.global_geometry_issues[0].reason,'unsafe_joint_not_stitched');
assert.equal(overlappingShort.global_geometry_issues[0].classification,'separate_offset_centers_but_road_strips_overlap');
assert.equal(overlappingShort.global_geometry_issues[0].local_strip_quad_overlap_2d,true);
assert.equal(overlappingShort.summary.global_nonoverlapping_unsafe_joints,0);
const disjointShort=shortSameWay(.000001);
assert.equal(disjointShort.global_geometry_issues[0].classification,'inspect_nonoverlapping_strips_at_native_connection');
assert.equal(disjointShort.summary.global_nonoverlapping_unsafe_joints,1,'a disjoint strip remains explicitly pending');
console.log('PASS: prepared 19/20 Avenida visual connector fixtures, native permissions, levels, short links and rigid-body invariance');
