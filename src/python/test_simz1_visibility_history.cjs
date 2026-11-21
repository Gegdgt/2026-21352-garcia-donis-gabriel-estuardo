'use strict';

// Isolated checks of the current production motion evaluator against seven
// historical SQLite records. No database, renderer, browser or server is opened.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const fixturePath = path.join(__dirname, 'fixtures', 'simz1-visibility-history.json');
const controlsPath = path.join(__dirname, 'visualizador_z1_controls.js');
const fixtureBytes = fs.readFileSync(fixturePath);
const controlsBytes = fs.readFileSync(controlsPath);
const fixture = JSON.parse(fixtureBytes.toString('utf8'));
const controls = controlsBytes.toString('utf8');
const start = controls.indexOf('const MOTION_STOP_TOLERANCE_KMH');
const end = controls.indexOf('function visualLaneText(', start);
assert(start >= 0 && end > start, 'Production motion evaluator boundaries changed; inspect before updating the test');
const {motionAt, centerPosition} = vm.runInNewContext(
  controls.slice(start, end) + '\n;({motionAt, centerPosition});',
  {}, {filename: controlsPath, timeout: 1000},
);

const expectedRun = 'simz1-0dd152dabbc24d1d84d9b738c449cc35';
assert.equal(fixture.source.run_id, expectedRun);
assert.equal(fixture.source.iteration, 0);
assert.equal(fixture.source.source_type, 'sqlite-direct-v1');
assert.equal(fixture.source.export_identity.run_id, expectedRun);
assert.equal(fixture.source.export_identity.iteration, '0');
assert.equal(fixture.cases.length, 3);
const originalFixture = JSON.stringify(fixture);
const byCase = new Map(fixture.cases.map(item => [item.case_id, item]));
const records = new Map(fixture.cases.flatMap(item => item.segments.map(segment =>
  [segment.sqlite_segment_id, segment.record])));
assert.equal(records.size, 7);
const active = (record, time) => record.timestamps[0] <= time && time < record.timestamps[1];
const assertAvailable = (record, time, message) => {
  const state = motionAt(record, time);
  assert.equal(state.available, true, message);
  assert(Number.isFinite(state.fraction) && state.fraction >= 0 && state.fraction <= 1);
  return state;
};

// The positive-duration terminal interval has no feasible continuous path.
// Its explicitly recorded link-entry instant remains available as a point;
// the open interval stays unavailable and no speed is inferred from that point.
const unavailableCase = byCase.get('unavailable_before_arrival_z1_43360');
const beforeUnavailable = records.get(927);
const unavailable = records.get(939);
assert.equal(unavailable.vehicle, 'z1_43360');
assert.deepEqual(unavailable.timestamps, [124, 125]);
assert.equal(unavailableCase.trip.Arrival, 125);
assert.equal(unavailableCase.trip.Status, 'completed');
assert.equal(beforeUnavailable.timestamps[1], unavailable.timestamps[0]);
assert(active(beforeUnavailable, 123.999));
assertAvailable(beforeUnavailable, 123.999, 'The preceding native interval must remain representable');
assert(unavailable.Motion_Plan.distance_m >
  unavailable.Motion_Plan.cap_mps * (unavailable.timestamps[1] - unavailable.timestamps[0]));
assert.equal(unavailable.Boundary_Provenance.start,'entered link');
assert.equal(unavailable.Boundary_Provenance.start_relative,0);
const entry=assertAvailable(unavailable,124,'The exact native link-entry event supplies its endpoint');
assert.equal(entry.source,'native_entered_link_at_exact_timestamp');
assert.equal(entry.status,'observed_event_position');
assert.equal(entry.instant_only,true);assert.equal(entry.fraction,0);assert.equal(entry.distance_m,0);
assert.equal(entry.speed_kmh,null);assert.equal(entry.acceleration_mps2,null);
assert.equal(entry.fallback_reason,'distance_exceeds_speed_cap');
assert.deepEqual(Array.from(centerPosition(unavailable,entry.fraction)),unavailable.path[0]);
for (const time of [124+Number.EPSILON*128,124.5,124.999]) {
  assert(active(unavailable, time));
  assert(time < unavailableCase.trip.Arrival);
  const state = motionAt(unavailable, time);
  assert.equal(state.available, false);
  assert.equal(state.fallback_reason, 'distance_exceeds_speed_cap');
}
assert.equal(active(unavailable, 125), false);

// Native mandatory waiting is available to the motion evaluator. This does NOT
// establish whether the separate body/queue/roster placement can display it.
const waitCase = byCase.get('short_link_native_wait_z1_38616');
const beforeWait = records.get(115);
const wait = records.get(151);
const afterWait = records.get(169);
assert.equal(wait.vehicle, 'z1_38616');
assert(wait.Distance_m > 0 && wait.Distance_m < 4.5);
assert.deepEqual(wait.timestamps, [39, 46]);
assert.equal(wait.Motion_Plan.hold_start, 41);
assert.equal(wait.Observed_Waits.priority_stop.first, 41);
assert.equal(wait.Observed_Waits.priority_stop.last, 45);
assertAvailable(beforeWait, 38.999);
assert.equal(assertAvailable(wait, 40.999).waiting, false);
for (const time of [41, 45.999]) {
  assert(active(wait, time));
  assert.equal(assertAvailable(wait, time).waiting, true);
}
assert.equal(active(wait, 46), false);
assert(active(afterWait, 46));
assertAvailable(afterWait, 46.001);
assert(waitCase.trip.Arrival > 46);

// The final zero-duration record is evidence, not a drawable interval. Its
// disappearance coincides with an explicitly recorded arrival, not an open trip.
const arrivalCase = byCase.get('arrival_zero_duration_z1_167074');
const beforeArrival = records.get(1682);
const zero = records.get(1684);
assert.equal(zero.vehicle, 'z1_167074');
assert.deepEqual(zero.timestamps, [169, 169]);
assert(zero.Distance_m > 0);
assert.equal(zero.Motion_Plan.status, 'unavailable');
assert.equal(zero.Motion_Plan.fallback_reason, 'zero_duration_positive_distance');
assert.equal(arrivalCase.trip.Status, 'completed');
assert.equal(arrivalCase.trip.Arrival, 169);
assertAvailable(beforeArrival, 168.999);
assert.equal(active(beforeArrival, 169), false);
assert.equal(active(zero, 169), false);
assert.equal(motionAt(zero, 169).available, false);

const summaries = fixture.cases.map(item => ({
  case_id: item.case_id,
  vehicle_id: item.segments[0].record.vehicle,
  person_id: item.trip.Person_ID,
  trip_id: item.trip.Trip_ID,
  arrival: item.trip.Arrival,
  trace: item.trace.map(row => {
    const candidates = item.segments.filter(segment => active(segment.record, row.simulated_time));
    assert.equal(candidates.length, row.native_active_interval_count);
    const record = candidates.length === 1 ? candidates[0].record : null;
    const state = record ? motionAt(record, row.simulated_time) : null;
    const position = state?.available ? Array.from(centerPosition(record, state.fraction)) : null;
    if (position && row.position_centerline_model_lonlat) {
      assert(position.every((value, index) => Math.abs(value - row.position_centerline_model_lonlat[index]) < 1e-10));
    }
    assert.equal(row.browser_visibility, 'not_observed');
    return {
      simulated_time: row.simulated_time,
      sqlite_segment_id: record ? candidates[0].sqlite_segment_id : null,
      link_id: row.link_id,
      native_lane_id: row.native_lane_id,
      position_centerline_model_lonlat: position,
      motion_available: state?.available ?? null,
      motion_reason: state?.fallback_reason ?? null,
      visibility_reason_from_fixture: row.visibility_reason,
      nominal_body_dimensions_m: row.client_nominal_dimensions_m,
      browser_visibility: 'not_observed',
    };
  }),
}));
assert.equal(JSON.stringify(fixture), originalFixture, 'Historical evidence must remain unchanged');
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
console.log(JSON.stringify({
  status: 'isolated_motion_assertions_completed',
  run_id: fixture.source.run_id,
  iteration: fixture.source.iteration,
  source_type: fixture.source.source_type,
  manifest_sha256: fixture.source.manifest_sha256,
  run_manifest_sha256: fixture.source.export_identity.run_manifest_sha256,
  fixture_sha256: sha256(fixtureBytes),
  current_controls_sha256: sha256(controlsBytes),
  evaluator_sha256: sha256(controls.slice(start, end)),
  browser_client_version: 'unknown; no browser opened',
  scope: 'Motion evaluator only; no body, queue roster, spatial filter or browser rendering evaluated',
  cases: summaries,
}, null, 2));
