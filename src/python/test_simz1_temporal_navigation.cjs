// Synthetic transport fixtures: no replay records or native runs are changed.
const assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const h=harness();h.api.pause();h.reply(0);await flush();
  h.api.seek(19337); // Exact requested second inside window 161.
  let elapsed=0;
  for(let attempt=0;attempt<40;attempt++) {
    h.reply(161,{error:'Servidor ocupado; reintente la ventana',retryable:true},503,'1');await flush();
    assert.equal(h.api.getState().error,null,'temporary saturation must not become a permanent failure');
    assert.equal(h.api.getState().current,0);
    assert.equal(h.api.getState().pendingTime,19337);
    assert.equal(h.api.getState().cache.pendingRequests,1);
    elapsed+=await h.retryTimer();h.setNow(elapsed);
  }
  assert.ok(elapsed>=300000,'synthetic wait exceeds five minutes');
  h.reply(161);await flush();
  assert.equal(h.api.getState().current,19337);assert.equal(h.api.getState().buffering,false);
  console.log('PASS synthetic: five-minute saturation recovers exact requested time without a retry-count failure');

  const slow=harness();slow.api.pause();slow.reply(0);await flush();
  slow.api.seek(12*3600+17);slow.frame(301000);
  assert.equal(slow.api.getState().current,0);assert.equal(slow.api.getState().pendingTime,43217);
  assert.equal(slow.api.getState().error,null);
  assert.match(slow.evaluate('continuousStatus.textContent'),/301 s/);
  assert.equal(slow.requests.filter(r=>r.url.includes('/api/window')).length,2,'long fetch must not be duplicated');
  slow.reply(360);await flush();assert.equal(slow.api.getState().current,43217);
  assert.equal(slow.api.getState().paused,true);
  console.log('PASS synthetic: live five-minute query keeps clock, pause and UI operative');

  const rapid=harness();rapid.api.pause();rapid.reply(0);await flush();
  const camera=JSON.stringify(rapid.api.getState().camera);
  rapid.api.setSpeed(1);
  for(const at of [36001,72005,18007,68409,12011])rapid.api.seek(at);
  for(const index of [300,600,150,570]) {
    assert.equal(rapid.request(index).options.signal.aborted,true);
    rapid.reply(index);await flush();
    assert.equal(rapid.api.getState().current,0,'late response cannot replace requested window');
  }
  rapid.reply(100);await flush();assert.equal(rapid.api.getState().current,12011);
  assert.equal(rapid.api.getState().speed,1);assert.equal(JSON.stringify(rapid.api.getState().camera),camera);
  assert.ok(rapid.api.getState().cache.peakPending<=2);
  assert.ok(rapid.api.getState().cache.cachedWindows<=3);
  assert.equal(rapid.api.getState().cache.pendingRequests,0);
  console.log('PASS synthetic: forward/backward rapid seeks cancel stale work and retain camera/speed');

  const speculative=harness();
  assert.equal(new URL(speculative.request(0).url,'http://localhost').searchParams.get('priority'),'demand');
  assert.equal(speculative.requests.length,1,'cold demand has priority over prefetch');
  speculative.reply(0);await flush();
  assert.equal(new URL(speculative.request(1).url,'http://localhost').searchParams.get('priority'),'prefetch');
  speculative.api.seek(14*3600);
  assert.equal(speculative.request(1).options.signal.aborted,true);
  assert.equal(new URL(speculative.request(420).url,'http://localhost').searchParams.get('priority'),'demand');
  speculative.reply(420);await flush();
  console.log('PASS synthetic: obsolete prefetch is cancelled and demand sent with explicit priority');

  for(const [status,body] of [[500,{error:'synthetic SQL failure',retryable:false}],
                            [503,{error:'synthetic persistent backend error',retryable:false}]]) {
    const failed=harness();failed.api.pause();failed.reply(0);await flush();failed.api.seek(60001);
    failed.reply(500,body,status);await flush();
    assert.match(failed.api.getState().error,/synthetic/);
    assert.equal(failed.api.getState().pendingTime,60001);assert.equal(failed.api.getState().current,0);
    assert.equal(failed.evaluate('continuousRetry.hidden'),false);assert.equal(failed.timers.size,0);
    failed.api.retry();failed.reply(500);await flush();assert.equal(failed.api.getState().current,60001);
  }
  for(const message of ['Failed to fetch: server closed','network connection interrupted']) {
    const failed=harness();failed.api.pause();failed.reply(0);await flush();failed.api.seek(72001);
    failed.request(600).reject(new TypeError(message));await flush();
    assert.equal(failed.api.getState().current,0);assert.ok(failed.api.getState().error);
    failed.api.retry();failed.reply(600);await flush();assert.equal(failed.api.getState().current,72001);
  }
  console.log('PASS synthetic: SQL errors, closed server and interrupted connection have explicit manual recovery');

  for(const override of [{run_id:'other-run'},{iteration:1},{run_manifest_sha256:'f'.repeat(64)},{source_version:'f'.repeat(64)}]) {
    const mixed=harness();mixed.api.pause();mixed.reply(0);await flush();mixed.api.seek(19337);
    mixed.reply(161,override);await flush();assert.ok(mixed.api.getState().error);
    assert.equal(mixed.api.getState().current,0);assert.equal(mixed.api.getState().cache.cachedWindows,1);
    mixed.api.retry();mixed.reply(161);await flush();assert.equal(mixed.api.getState().current,19337);
  }
  const truncated=harness();truncated.api.pause();
  const req=truncated.request(0);req.replied=true;
  req.resolve({ok:true,status:200,headers:{get:name=>name==='X-SimZ1-JSON-Bytes' ? '999999' : null},text:async()=>JSON.stringify(truncated.payload(0))});
  await flush();assert.match(truncated.api.getState().error,/truncada/);
  assert.equal(truncated.api.getState().cache.cachedWindows,0);
  truncated.api.retry();truncated.reply(0);await flush();assert.equal(truncated.api.getState().buffering,false);
  console.log('PASS synthetic: run/iteration/manifest/source identity and full response length fail closed');
})().catch(error=>{console.error(error);process.exitCode=1;});
