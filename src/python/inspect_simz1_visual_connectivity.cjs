/* Read-only renderer audit. JSON stdin is effective visual_lanes plus explicit
 * focus_link_ids; stdout contains evidence, never modified network geometry. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const VisualLanes=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VisualLanes;');
const SpatialView=require('./simz1_spatial_view.js');

// Conservative local-plane strip rectangles: these diagnose centreline warnings
// against the actual metric road widths, without claiming a GPU/pixel inspection.
function stripQuads(row,projection) {
  const {origin,xScale,yScale}=projection;
  const points=row.path.map(p=>[(p[0]-origin[0])*xScale,(p[1]-origin[1])*yScale]),quads=[];
  for(let i=1;i<points.length;i++) {
    const a=points[i-1],b=points[i],dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
    if(!length)continue;
    const nx=dy/length*row.width_m/2,ny=-dx/length*row.width_m/2;
    quads.push([[a[0]+nx,a[1]+ny],[b[0]+nx,b[1]+ny],[b[0]-nx,b[1]-ny],[a[0]-nx,a[1]-ny]]);
  }
  return quads;
}
function overlap(a,b) {
  for(const polygon of [a,b])for(let i=0;i<polygon.length;i++) {
    const p=polygon[i],q=polygon[(i+1)%polygon.length],nx=q[1]-p[1],ny=p[0]-q[0];
    const left=a.map(v=>v[0]*nx+v[1]*ny),right=b.map(v=>v[0]*nx+v[1]*ny);
    if(Math.max(...left)<Math.min(...right)-1e-8 || Math.max(...right)<Math.min(...left)-1e-8)return false;
  }
  return true;
}

function inspect(input) {
  const metadata=input?.visual_lanes,ids=input?.focus_link_ids;
  if(metadata?.schema_version!==1 || metadata.available!==true || !metadata.links ||
     !Array.isArray(ids) || !ids.length || ids.length>2000 ||
     ids.some(id=>typeof id!=='string' || !id) || new Set(ids).size!==ids.length)
    throw new Error('Effective visual_lanes and 1..2000 unique focus_link_ids required');
  const renderer=new VisualLanes(metadata),focus=new Set(ids);
  const spatial=input.spatial_demand ? new SpatialView(input.spatial_demand,metadata.identity) : null;
  const roads=renderer.roads(),connectors=renderer.connectors(),snapshot=renderer.snapshot();
  const countReasons=rows=>rows.reduce((counts,row)=>{counts[row.reason]=(counts[row.reason] || 0)+1;return counts;},{});
  const visibleRoads=spatial ? spatial.paths(roads.filter(row=>spatial.allowed.has(row.Link_ID))) : roads;
  const visibleConnectors=spatial ? spatial.paths(connectors.filter(row=>
    spatial.allowed.has(row.Link_ID) && spatial.allowed.has(row.To_Link_ID))) : connectors;
  const byLink=rows=>{const groups=new Map();for(const row of rows) {
    if(!groups.has(row.Link_ID))groups.set(row.Link_ID,[]);groups.get(row.Link_ID).push(row);
  }return groups;};
  const roadGroups=byLink(roads),visibleGroups=byLink(visibleRoads),connectorGroups=byLink(connectors);
  const visibleConnectorGroups=byLink(visibleConnectors),movements=[],missing=[],links=[];
  const globalIssues=snapshot.issues.filter(row=>row.reason!=='reversing_visual_connector_without_supported_curve');
  const inspectedGlobalIssues=globalIssues.slice(0,100).map(issue=>{
    const a=renderer.links.get(issue.Link_ID),b=renderer.links.get(issue.To_Link_ID);
    if(Array.isArray(issue.Link_IDs)) {
      const chain=issue.Link_IDs.map(id=>renderer.links.get(id));
      return {...issue,source_way:a?.data.source_way,link_count:chain.length,
        all_native_axes_retained:chain.every(link=>link && !link.eligible),
        consecutive_native_nodes_match:chain.slice(1).every((link,i)=>chain[i]?.data.to_node===link?.data.from_node),
        classification:'native_axis_fallback_no_joined_offset'};
    }
    if(!a?.geometry || !b?.geometry)return {...issue,classification:'missing_visual_geometry'};
    const left=roadGroups.get(a.id) || [],right=roadGroups.get(b.id) || [];
    const gaps=left.flatMap(before=>right.map(after=>{
      const p=before.path.at(-1),q=after.path[0];
      return Math.hypot((p[0]-q[0])*a.geometry.xScale,(p[1]-q[1])*a.geometry.yScale);
    }));
    const gap=gaps.length ? Math.min(...gaps) : null;
    const qa=left.flatMap(row=>stripQuads(row,renderer.projection)),qb=right.flatMap(row=>stripQuads(row,renderer.projection));
    const stripOverlap=qa.some(u=>qb.some(v=>overlap(u,v)));
    return {...issue,source_way:a.data.source_way,highway:a.data.osm_tags?.highway,name:a.data.osm_tags?.name ?? null,
      via_node:a.data.to_node,shared_native_node:a.data.to_node===b.data.from_node,
      compatible_level_tags:renderer.compatibleLevel(a,b),position:a.data.path.at(-1),
      source_lengths_m:[a.geometry.length,b.geometry.length],
      minimum_drawn_endpoint_gap_m:gap,local_strip_quad_overlap_2d:stripOverlap,
      classification:!a.eligible && !b.eligible ? 'native_axis_fallback_shared_endpoint' :
        gap!==null && gap<=1e-5 ? 'drawn_endpoints_coincident' : stripOverlap ?
          'separate_offset_centers_but_road_strips_overlap' : 'inspect_nonoverlapping_strips_at_native_connection'};
  });
  for(const id of [...ids].sort()) {
    const a=renderer.links.get(id);
    if(!a){missing.push(id);continue;}
    links.push({id,from_node:a.data.from_node,to_node:a.data.to_node,source_way:a.data.source_way,
      name:a.data.osm_tags?.name ?? null,geometry_source:a.data.geometry_source ?? null,
      native_endpoints:[a.data.path?.[0],a.data.path?.at(-1)],offset_eligible:a.eligible,
      road_strips:roadGroups.get(id)?.length || 0,visible_pieces:visibleGroups.get(id)?.length || 0,
      allowed_by_spatial_domain:spatial ? spatial.allowed.has(id) : null});
    const targets=new Map();
    for(let index=0;index<a.lanes;index++)for(const target of renderer.targets(a,index)) {
      if(!targets.has(target))targets.set(target,[]);targets.get(target).push(index);
    }
    for(const [target,indices] of [...targets].sort((x,y)=>x[0].localeCompare(y[0]))) {
      const b=renderer.links.get(target);
      if(!a.geometry || !b?.geometry)continue;
      const shared=a.data.to_node!=null && a.data.to_node===b.data.from_node;
      const sameLevel=renderer.compatibleLevel(a,b),u=a.geometry.edges.at(-1),v=b.geometry.edges[0];
      const reversing=b.data.to_node===a.data.from_node || u.dx*v.dx+u.dy*v.dy<=-.95;
      const rows=(connectorGroups.get(id) || []).filter(row=>row.To_Link_ID===target);
      const visible=(visibleConnectorGroups.get(id) || []).filter(row=>row.To_Link_ID===target);
      const gaps=[];
      if(a.eligible && b.eligible)for(const index of indices)for(let j=0;j<b.lanes;j++) {
        const p=renderer.sample(a.geometry,1,renderer.offset(a,index));
        const q=renderer.sample(b.geometry,0,renderer.offset(b,j));
        if(p && q)gaps.push(Math.hypot((p.position[0]-q.position[0])*a.geometry.xScale,
          (p.position[1]-q.position[1])*a.geometry.yScale));
      }
      const gap=gaps.length ? Math.min(...gaps) : null;
      movements.push({from_link:id,to_link:target,via_node:a.data.to_node,
        permission_source:a.data.movement_source,shared_native_node:shared,compatible_level_tags:sameLevel,
        u_turn_or_reversal:reversing,minimum_offset_endpoint_gap_m:gap,
        // This minimum only diagnoses strip endpoints. It assigns no target lane.
        target_lane_ambiguous:b.lanes>1 && a.assignmentKey!==b.assignmentKey,
        connectors:rows.length,visible_connectors:visible.length,
        connector_sources:[...new Set(rows.map(row=>row.source))],
        inset_setbacks_m:[...new Set(rows.filter(row=>row.setback_m!=null).map(row=>row.setback_m))],
        classification:!shared ? 'nonadjacent_target' : !sameLevel ? 'grade_tags_preserved_no_connector' :
          reversing ? 'native_reversal_not_evidence_for_new_join' : rows.length ? 'visual_connector_present' :
          gap!==null && gap<=1e-5 ? 'offset_endpoints_coincident' : 'inspect_unrepresented_visual_movement'});
    }
  }
  return {schema:'simz1-visual-connectivity-inspection-v1',read_only:true,
    identity:metadata.identity,sources:metadata.sources || {},spatial_clipping_active:!!spatial,
    summary:{renderer_version:snapshot.version,roads:snapshot.roads,connectors:snapshot.connectors,
      inferred_single_lane_turn_connectors:snapshot.inferredSingleLaneTurnConnectors,
      ambiguous_target_lane_movements:snapshot.ambiguousTargetLaneMovements,
      reversing_connectors_omitted:snapshot.reversingConnectorsOmitted,
      geometry_issue_counts:countReasons(snapshot.issues),
      inspected_global_geometry_issues:inspectedGlobalIssues.length,
      global_nonoverlapping_unsafe_joints:inspectedGlobalIssues.filter(row=>
        row.classification==='inspect_nonoverlapping_strips_at_native_connection').length,
      focused_links:links.length,
      focused_native_movements:movements.length,
      focused_unrepresented_nonreversing_movements:movements.filter(row=>
        row.classification==='inspect_unrepresented_visual_movement').length},
    missing_focus_links:missing,links,movements,
    global_geometry_issues:inspectedGlobalIssues,global_geometry_issues_limit:100,
    global_geometry_issues_truncated:globalIssues.length>100,
    focused_geometry_issues:snapshot.issues.filter(row=>focus.has(row.Link_ID)),
    limitations:['Rendered paths are computed without WebGL or browser execution.',
      'Native lane permission does not certify enforcement of pending OSM restrictions.',
      'Endpoint distances do not assign target lanes or justify proximity-based connections.',
      'Local metric strip overlap is a geometry check, not a GPU/pixel or complete junction-footprint inspection.']};
}

if(require.main===module) {
  try {
    const raw=fs.readFileSync(0,'utf8');
    if(Buffer.byteLength(raw,'utf8')>32*1024*1024)throw new Error('Inspection input exceeds 32 MiB');
    console.log(JSON.stringify(inspect(JSON.parse(raw))));
  } catch(error) {console.error(error.message);process.exitCode=1;}
}
module.exports={inspect};
