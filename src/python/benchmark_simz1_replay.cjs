// CPU/heap of actual replay code with DOM/deck stubs. No WebGL or FPS claim.
const fs=require('fs'),vm=require('vm'),{performance}=require('perf_hooks');
const sizes=process.argv.slice(2).map(Number);
const results=[];
for(const count of sizes.length?sizes:[10000,172886])for(const dense of [false,true]) {
  const records=Array.from({length:count},(_,i)=>{
    const t=dense?0:i*86300/count;
    return {vehicle:'v'+i,Agent_ID:'p'+i,timestamps:[t,t+180],Movement_End:t+180,
      Speed_kmh:20,Motion_Speed_kmh:20,path:[[0,0],[1,0]],color:[255,210,40]};
  });
  const layer={id:'trips',props:{data:records},clone(p){return {...this,props:{...this.props,...p}};}};
  const sandbox={performance,requestAnimationFrame:()=>{},config:{},replaySegments:records,incidentRecords:[],layers:[layer],
    document:{hidden:false,createElement:()=>({style:{},append(){},setAttribute(){}}),body:{appendChild(){}},addEventListener(){}},
    deckInstance:{setProps(){}}};
  const before=process.memoryUsage();const start=performance.now();
  vm.createContext(sandbox);vm.runInContext(fs.readFileSync('python/visualizador_z1_controls.js','utf8'),sandbox);
  const initialization=performance.now()-start;
  const samples=[];let active=0;
  for(let i=0;i<16;i++){
    sandbox.probeTime=dense?80+i:43000+(i%2?i:-i)*30;
    const t=performance.now();vm.runInContext('current=probeTime;render();',sandbox);
    samples.push(performance.now()-t);active=vm.runInContext('activeAgentCount',sandbox);
  }
  const times=samples.slice(3).sort((a,b)=>a-b),after=process.memoryUsage();
  results.push({vehicles:count,simultaneously_active:dense,active_last_sample:active,initialization_ms:initialization,
    render_stub_p50_ms:times[Math.floor(times.length*.5)],render_stub_p95_ms:times[Math.floor(times.length*.95)],
    heap_used_bytes:after.heapUsed,heap_delta_bytes:after.heapUsed-before.heapUsed,rss_bytes:after.rss,
    gpu_measured:false,note:'Actual JS render/marker/index with stub DOM and deck; no browser paint or FPS measurement'});
  console.log(JSON.stringify(results[results.length-1]));
}
fs.mkdirSync('target/prompt7-benchmark',{recursive:true});
fs.writeFileSync('target/prompt7-benchmark/javascript.json',JSON.stringify(results,null,2));
