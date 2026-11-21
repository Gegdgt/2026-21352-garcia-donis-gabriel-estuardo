'use strict';

// Authoritative DOM-only check of the preserved synthetic QA export.
// Historical predecessor: audits/prompt11/check-fixture-controls.cjs.
// This evaluates the supplied HTML's embedded code, not today's viewer sources.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const assert=require('node:assert/strict'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'../..');
const DEFAULT_HTML=path.join(ROOT,'tests/fixtures/replay/fixture-replay.html');
const MAX_HTML_BYTES=2*1024*1024;
const USAGE='node scripts/validation/check_motion_fixture_controls.cjs [--html PATH] [--output PATH]\n'+
  'Default HTML: tests/fixtures/replay/fixture-replay.html\n'+
  'Default output: runtime/validation/motion-fixture-controls-<UTC>.json (new file only)\n'+
  'Checks trusted synthetic HTML with DOM/Deck stubs; no browser, server or QSim.\n';

function parseArguments(argv) {
  const result={html:DEFAULT_HTML,output:null,help:false},seen=new Set();
  for(let i=0;i<argv.length;i++) {
    const key=argv[i];
    if(key==='--help') {if(argv.length!==1)throw new Error('--help must be used alone');result.help=true;continue;}
    if(!['--html','--output'].includes(key))throw new Error('Unknown option: '+key);
    if(seen.has(key))throw new Error('Repeated option: '+key);
    seen.add(key);
    const value=argv[++i];
    if(!value || value.startsWith('--'))throw new Error('Missing path after '+key);
    result[key.slice(2)]=path.resolve(value);
  }
  return result;
}

function extractFixture(html) {
  const payload=html.match(/<script id="replay-data" type="application\/json">([\s\S]*?)<\/script>/);
  if(!payload)throw new Error('Missing replay-data JSON in synthetic fixture HTML');
  JSON.parse(payload[1]);
  const script=html.match(/<script>\s*([\s\S]*?)<\/script>/);
  if(!script)throw new Error('Missing inline fixture controls script');
  return {payload:payload[1],script:script[1]};
}

function checkFixture(html) {
  const {payload,script}=extractFixture(html);
  const buttons=[],elements=new Map(),allElements=[];
  let clock=0,nextFrame=null,latestDeck=null;
  function element(tag) {
    const value={tag,style:{},dataset:{},children:[],value:'',setAttribute(){},
      append(...children){this.children.push(...children);},appendChild(child){this.children.push(child);},addEventListener(){}};
    Object.defineProperty(value,'id',{set(id){this.ident=id;elements.set(id,this);},get(){return this.ident;}});
    if(tag==='button')buttons.push(value);
    allElements.push(value);return value;
  }
  const replay=element('script');replay.textContent=payload;elements.set('replay-data',replay);
  elements.set('load-status',element('div'));elements.set('deck-container',element('div'));
  class Layer {constructor(props){this.id=props.id;this.props=props;}clone(props){return new Layer({...this.props,...props});}}
  class Deck {constructor(props){this.props=props;latestDeck=this;}setProps(props){Object.assign(this.props,props);}}
  const deck={Deck,PathLayer:Layer,LineLayer:Layer,ScatterplotLayer:Layer,IconLayer:Layer};
  const sandbox={console,Map,Math,String,deck,window:{deck},performance:{now:()=>clock},
    requestAnimationFrame(callback){nextFrame=callback;},
    document:{hidden:false,createElement:element,getElementById:id=>elements.get(id),body:element('body'),addEventListener(){}}};
  vm.createContext(sandbox);
  vm.runInContext(script,sandbox,{timeout:10000,filename:'supplied-synthetic-fixture.js'});
  const results=[];
  const labels=['Freno inicio','Freno final','Espera inmovil','Aceleracion','Lento 10 rojo','Datos insuficientes','Medianoche',
    'Guardar muestra','Retroceder','Misma muestra 1x','Misma muestra 120x','40 km/h supuesto','40 hacia cero','Cero matematico'];
  for(const label of labels) {
    const matches=buttons.filter(item=>item.parent===undefined && item.textContent===label);
    assert.equal(matches.length,1,'Expected exactly one fixture control: '+label);
    assert.equal(typeof matches[0].onclick,'function','Missing callback: '+label);
    matches[0].onclick();
    const result=elements.get('motion-fixture-result');
    assert.ok(result,'Missing fixture result element');
    results.push({button:label,result:result.dataset.result,detail:result.textContent});
    assert.equal(result.dataset.result,'pass',result.textContent);
  }
  const button=label=>buttons.find(item=>item.textContent===label);
  const seeker=allElements.find(item=>item.tag==='input' && item.type==='range');
  const toggle=button('Reproducir');
  assert.ok(seeker && typeof seeker.oninput==='function','Missing fixture seek control');
  assert.ok(toggle && typeof toggle.onclick==='function','Missing playback control');
  const marker=()=>latestDeck?.props.layers.find(layer=>layer.id==='trips')?.props.data.find(row=>row.vehicle==='vehicle_free');
  const animations=[];
  function assertAt(time,label) {
    const point=marker();assert.ok(point,label+' must retain visible free vehicle');
    assert.ok(Math.abs(Number(seeker.value)-time)<1e-8,label+' uses absolute simulated seconds');
    assert.ok(Math.abs(point.position[1]-(14.636+.0009*time/20))<1e-10,label+' retains authored fixture position');
    assert.ok(Math.abs(point.Visual_Speed_kmh-18)<1e-8,label+' speed must not multiply by playback rate');
    animations.push({label,time:Number(seeker.value),speed_kmh:point.Visual_Speed_kmh,position:point.position.slice(),result:'pass'});
  }
  button('Misma muestra 1x').onclick();clock=1000;toggle.onclick();clock=2000;nextFrame(clock);assertAt(13,'1x one real second');
  toggle.onclick();clock=10000;nextFrame(clock);assertAt(13,'pause freezes time and position');
  toggle.onclick();clock=10500;nextFrame(clock);assertAt(13.5,'resume 1x adds only unpaused interval');
  button('Misma muestra 120x').onclick();clock=11000;toggle.onclick();clock=11050;nextFrame(clock);assertAt(18,'120x 50 ms advances six simulated seconds');
  toggle.onclick();seeker.value=12;seeker.oninput();assertAt(12,'paused reverse seek restores exact sample');
  return {schema_version:1,status:'passed',
    scope:'Preserved synthetic HTML: 7 event actors plus 1 mathematical reference; embedded historical viewer only',
    current_viewer_sources_validated:false,browser_rendering_verified:false,matsim_executed:false,
    source:'Node DOM/Deck stubs; authored geometry and waits are not calibrated measurements',
    results,animations};
}

function main(argv=process.argv.slice(2)) {
  const options=parseArguments(argv);
  if(options.help){process.stdout.write(USAGE);return null;}
  const input=path.resolve(options.html);
  const stamp=new Date().toISOString().replace(/[-:.]/g,'');
  const output=options.output || path.join(ROOT,'runtime/validation','motion-fixture-controls-'+stamp+'.json');
  const canonical=value=>process.platform==='win32'?path.resolve(value).toLowerCase():path.resolve(value);
  if(canonical(input)===canonical(output))throw new Error('Output must not replace the input HTML');
  if(fs.existsSync(output))throw new Error('Output already exists; choose a new --output path');
  const stat=fs.statSync(input);
  if(!stat.isFile() || stat.size>MAX_HTML_BYTES)throw new Error('Expected a small fixture HTML file (maximum 2 MiB), not a production export');
  const bytes=fs.readFileSync(input),report=checkFixture(bytes.toString('utf8'));
  report.input_html=path.relative(ROOT,input).split(path.sep).join('/');
  report.input_sha256=crypto.createHash('sha256').update(bytes).digest('hex');
  report.checked_at_utc=new Date().toISOString();
  fs.mkdirSync(path.dirname(output),{recursive:true});
  fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{encoding:'utf8',flag:'wx'});
  console.log('PASS: 14 synthetic fixture controls and 5 timed playback/seek checks; historical embedded HTML only.');
  console.log('Report: '+path.relative(ROOT,output).split(path.sep).join('/'));
  return report;
}

module.exports={parseArguments,extractFixture,checkFixture,main,DEFAULT_HTML,MAX_HTML_BYTES};
if(require.main===module) {
  try {main();} catch(error) {console.error('FAIL: '+error.message);process.exitCode=1;}
}
