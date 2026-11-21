// Paste in the ALREADY OPEN viewer console. Defines a function, does not start it.
window.runSimZ1IntegrationBenchmark=async function({expectedBuild,times=[28080,43200,64800],seconds=3}={}) {
  const api=window.simz1Continuous;
  if(!api || !expectedBuild || window.simz1ClientBuild?.source_sha256!==expectedBuild)throw new Error('Loaded client differs from reviewed sources');
  if(!Array.isArray(times) || !times.length || times.some(t=>!Number.isFinite(t) || t<0 || t>86400) ||
     !Number.isFinite(seconds) || seconds<1 || seconds>10)throw new Error('Explicit times 0..86400 and seconds 1..10 required');
  const initial=api.getState(),initialPerf=api.getPerformance(),sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const identity=JSON.stringify([initialPerf.run_id,initialPerf.iteration,initialPerf.run_manifest_sha256]);
  const report={status:'running',client:window.simz1ClientBuild,identity:initialPerf,cases:[],
    environment:{userAgent:navigator.userAgent,hardwareConcurrency:navigator.hardwareConcurrency,
      devicePixelRatio:window.devicePixelRatio,width:window.innerWidth,height:window.innerHeight},
    scope:'Existing-tab CPU/RAF/window/heap observations, not GPU execution or guaranteed FPS. No feature disabled.',
    closure:'Restores clock/rate/pause and clears benchmark selection; never closes the user tab/server. Loader destruction measured in separate CPU fixture.'};
  const ready=async()=>{const deadline=performance.now()+120000;
    while(api.getState().buffering){if(performance.now()>deadline)throw new Error('Window activation timeout');await sleep(50);}
    if(api.getState().error)throw new Error(api.getState().error);
    const p=api.getPerformance();if(JSON.stringify([p.run_id,p.iteration,p.run_manifest_sha256])!==identity)throw new Error('Run identity changed');};
  try {
    api.pause();api.clearSelection();
    for(const time of times)for(const speed of [1,120]) {
      const before=api.getPerformance(),seekStarted=performance.now();api.seek(time);
      const buffered=api.getState().buffering;await ready();const seekMs=performance.now()-seekStarted;
      api.setSpeed(speed);api.resetRenderMetrics();api.play();await sleep(seconds*1000);api.pause();await ready();
      const frame=api.getRenderPerformance(),after=api.getPerformance();
      report.cases.push({time,speed,seekMs,buffered,before,after,render:frame,
        camera:api.getState().camera,frameCadenceMs:frame.frames.slice(1).map((row,index)=>row.wallTime-frame.frames[index].wallTime),
        observedVisible:api.getState().visibleMarkers,activePublicVehicles:api.getState().activePublicVehicles,
        arrivalAnnotations:api.getArrivalDiagnostics().active?.length ?? null,
        densityLabel:'Measured visible count; these times are candidates, not presumed dense windows.'});
      api.seek(time);await ready();
      if(api.selectActive(0)) {
        const deadline=performance.now()+120000;
        while(api.getState().selectedJourneyStatus==='loading'){if(performance.now()>deadline)throw new Error('Journey timeout');await sleep(50);}
        if(api.getState().selectedJourneyStatus!=='complete')throw new Error('Selected journey unavailable');
        const requests=api.getPerformance().selectionRequests.started;
        for(let i=0;i<10;i++)api.selectActive(0);
        if(api.getPerformance().selectionRequests.started!==requests)throw new Error('Repeated selection requested journey again');
      }
      api.clearSelection();api.seek(Math.max(0,time-120));await ready();
    }
    api.seek(86400);await ready();report.dayEnd=api.getState();report.status='complete';
  } catch(error){report.status='failed';report.error=String(error.stack || error);throw error;}
  finally {
    window.simz1IntegrationBenchmark=report;
    try {
      api.pause();api.clearSelection();api.seek(initial.current);await ready();api.setSpeed(initial.speed);
      if(!initial.paused)api.play();report.final=api.getPerformance();
    } catch(error){report.status='failed';report.restoreError=String(error);}
    console.log('Saved window.simz1IntegrationBenchmark; copy(JSON.stringify(window.simz1IntegrationBenchmark,null,2))');
  }
  return report;
};
