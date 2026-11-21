// In-memory source geometry and screen projection; no browser, server or run IO.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const Lanes=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VisualLanes;',{});
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],links={};
for(let i=0;i<6;i++) {
  const road={num_lanes:1,path:[xy(i*100,0),xy((i+1)*100,0)],osm_tags:{name:'7a Avenida'},offset_eligible:true};
  links['a'+i]=road;links['r'+i]={...road,path:[...road.path].reverse()};
}
links.cross={num_lanes:1,path:[xy(350,-120),xy(350,120)],osm_tags:{name:'12 Calle'},offset_eligible:true};
links.unnamed={num_lanes:1,path:[xy(0,60),xy(600,60)],osm_tags:{},offset_eligible:true};
const options={schema_version:1,links,landmarks:[
  {name:'Museo de prueba',position:xy(400,160),source:'recorded_osm_node'},
  {name:'Sin respaldo',position:xy(100,160),source:'invented'}]};
const before=JSON.stringify(options),lanes=new Lanes(options),project=p=>[100+p[0]*scale,300-p[1]*scale];
const frame=zoom=>lanes.labels({zoom},project,900,600);
assert.equal(frame(14.99).length,0,'far zoom hides all labels');
assert.equal(frame(15).filter(r=>r.name==='7a Avenida').length,1,'one label at intermediate zoom despite 12 named links');
assert.equal(frame(15).filter(r=>r.kind==='landmark').length,0);
const detailed=frame(17);
assert.equal(detailed.filter(r=>r.name==='7a Avenida').length,2,'at most two end labels for the entire named street, including reverse links');
assert.equal(detailed.filter(r=>r.name==='Museo de prueba').length,1);
assert.ok(detailed.every(r=>r.name!=='Sin respaldo' && r.name!=='unnamed'));
assert.ok(detailed.every(r=>r.angle>=-90 && r.angle<=90),'text never faces upside down');
const cross=detailed.find(r=>r.name==='12 Calle');assert.ok(cross);assert.ok(Math.abs(cross.angle)===90);
const rotated=lanes.labels({zoom:17},p=>{const [x,y]=project(p);return [900-x,600-y];},900,600);
assert.ok(rotated.every(r=>r.angle>=-90 && r.angle<=90),'camera rotation preserves upright text');
const packed=lanes.labels({zoom:17},()=>[450,300],900,600);
assert.equal(packed.length,1,'colliding text boxes share a single label');
assert.equal(lanes.labels({zoom:17},project,900,600,()=>false).length,0,'spatial clipping also filters labels');
assert.equal(lanes.labels({zoom:17},project,900,600,()=>true,new Set()).filter(r=>r.kind==='road').length,0);
const interior=lanes.labels({zoom:17},p=>[p[0]*scale-100,300-p[1]*scale],350,600);
assert.ok(interior.some(r=>r.name==='7a Avenida'),'strategic middle fallback when both street ends leave the viewport');
assert.ok(interior.some(r=>r.name==='12 Calle'),'finding an alternative must preserve the crossing street label');
function assertSparse(rows,project,width,height,limit) {
  const boxes=[],counts=new Map();
  for(const row of rows) {
    const p=project(row.position),angle=row.angle*Math.PI/180,[dx,dy]=row.pixelOffset;
    const textWidth=row.name.length*8.5+12;
    const rx=(Math.abs(Math.cos(angle))*textWidth+Math.abs(Math.sin(angle))*18)/2+6;
    const ry=(Math.abs(Math.sin(angle))*textWidth+Math.abs(Math.cos(angle))*18)/2+6;
    const box=[p[0]+dx-rx,p[1]+dy-ry,p[0]+dx+rx,p[1]+dy+ry];
    assert.ok(box[0]>=8 && box[1]>=8 && box[2]<=width-8 && box[3]<=height-8,'complete text fits viewport');
    assert.ok(boxes.every(b=>box[0]>=b[2] || box[2]<=b[0] || box[1]>=b[3] || box[3]<=b[1]),'alternative text never overlaps');
    boxes.push(box);counts.set(row.name,(counts.get(row.name) || 0)+1);
    assert.ok(counts.get(row.name)<=limit,'alternatives do not add label density');
    if(row.kind==='road')assert.ok(Math.hypot(dx,dy)>=16,'road labels offset from street centre');
  }
}
assertSparse(detailed,project,900,600,2);
assertSparse(interior,p=>[p[0]*scale-100,300-p[1]*scale],350,600,2);
assertSparse(frame(15),project,900,600,1);
// Also rescue an unsplit long OSM link: endpoints are offscreen and the
// midpoint collides, so the alternative must lie inside that same link.
const unsplit=new Lanes({schema_version:1,links:{
  avenue:{num_lanes:1,path:[xy(0,0),xy(600,0)],osm_tags:{name:'7a Avenida'},offset_eligible:true},
  cross:{...links.cross,path:[xy(300,-120),xy(300,120)]}}});
const interiorProject=p=>[p[0]*scale-100,300-p[1]*scale];
const rescued=unsplit.labels({zoom:17},interiorProject,350,600);
assert.equal(rescued.filter(r=>r.name==='7a Avenida').length,1,'search within a long link after centre collision');
assert.ok(rescued.some(r=>r.name==='12 Calle'));
assertSparse(rescued,interiorProject,350,600,2);
assert.equal(JSON.stringify(interior),JSON.stringify(lanes.labels({zoom:17},
  p=>[p[0]*scale-100,300-p[1]*scale],350,600)),'placement remains deterministic');
assert.equal(new Lanes({schema_version:1,links:{blank:links.unnamed}}).labels({zoom:17},project,900,600).length,0);
assert.equal(JSON.stringify(options),before,'source names and coordinates remain immutable');
console.log('PASS: source-only names/places, sparse endpoints, zoom, camera orientation, screen collisions and clipping');
