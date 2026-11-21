'use strict';
// Pure CLI parsing and DOM-stub fixture checks. No server, browser, QSim or output file.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const checker=require('../scripts/validation/check_motion_fixture_controls.cjs');
assert.equal(checker.parseArguments([]).html,checker.DEFAULT_HTML);
assert.equal(checker.parseArguments(['--help']).help,true);
const custom=checker.parseArguments(['--html','folder with spaces/replay.html','--output','folder with spaces/report.json']);
assert.equal(custom.html,path.resolve('folder with spaces/replay.html'));
assert.equal(custom.output,path.resolve('folder with spaces/report.json'));
for(const args of [['--html'],['--output','--html'],['--unknown'],['--html','a','--html','b'],['--help','--html','a']])
  assert.throws(()=>checker.parseArguments(args));
assert.throws(()=>checker.extractFixture('<html></html>'),/Missing replay-data/);
assert.throws(()=>checker.extractFixture('<script id="replay-data" type="application/json">{broken}</script>'),SyntaxError);
assert.throws(()=>checker.extractFixture('<script id="replay-data" type="application/json">{}</script>'),/Missing inline/);
const report=checker.checkFixture(fs.readFileSync(checker.DEFAULT_HTML,'utf8'));
assert.equal(report.results.length,14);
assert.equal(report.animations.length,5);
assert.equal(report.current_viewer_sources_validated,false);
assert.equal(report.browser_rendering_verified,false);
assert.equal(report.matsim_executed,false);
console.log('PASS: explicit paths, invalid input and preserved synthetic HTML; no current-viewer or WebGL validation claim.');
