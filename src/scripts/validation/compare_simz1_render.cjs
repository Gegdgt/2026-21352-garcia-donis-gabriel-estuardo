'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const [beforePath,afterPath]=process.argv.slice(2);
if(!beforePath || !afterPath)throw new Error('Usage: node compare_simz1_render.cjs before.json after.json');
const before=JSON.parse(fs.readFileSync(beforePath)),after=JSON.parse(fs.readFileSync(afterPath));
if(before.error || after.error)throw new Error(before.error || after.error);
const key=row=>[row.count,row.mode,row.operation].join('/'),old=new Map(before.cases.map(row=>[key(row),row]));
const results=[];
for(const row of after.cases) {
  const previous=old.get(key(row));assert.ok(previous,'missing comparable case');
  assert.equal(row.visible,previous.visible,'visible count changed '+key(row));
  assert.equal(row.active,previous.active,'active count changed '+key(row));
  const prior=new Map(previous.positions.map(p=>[p[0],p]));
  for(const [id,position,heading] of row.positions) {
    const p=prior.get(id);assert.ok(p,'identity lost '+id);
    assert.ok(position.every((v,i)=>Math.abs(v-p[1][i])<1e-9),'position changed '+key(row)+' '+id);
    assert.ok(Math.abs(heading-p[2])<1e-7,'heading changed '+id);
  }
  results.push({case:key(row),before_p95_ms:previous.p95Ms,after_p95_ms:row.p95Ms,
    p95_change_pct:(row.p95Ms/previous.p95Ms-1)*100,
    before_sampled_allocated:previous.sampledAllocatedBytes,after_sampled_allocated:row.sampledAllocatedBytes,
    before_heap:previous.heapUsed,after_heap:row.heapUsed,
    before_gc_ms:previous.gc.reduce((s,r)=>s+r.duration,0),after_gc_ms:row.gc.reduce((s,r)=>s+r.duration,0)});
}
assert.equal(results.length,old.size);console.table(results);
console.log('CPU-only results. Validate presented FPS and GPU work in Chrome/Edge separately.');
