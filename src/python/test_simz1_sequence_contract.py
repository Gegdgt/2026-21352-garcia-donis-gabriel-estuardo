"""Correction 7: bounded routing regressions, never Controller/QSim or a launch.

Runs the repaired original Java probe, source/mutation checks, 115 existing OD
pairs and 99 private test trips. 180K is checked by arithmetic only.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import xml.etree.ElementTree as ET

from simz1_sequence_contract import (ROOT, CONTRACT, SHA256, SequenceContract,
    load_contract, relation_identity, malformed_disposition)
from simz1_balanced_od import BalancedGatewayModel, load_model
from simz1_od_policy import validate_osm_turns, named_percentages, CLASS_BY_TYPE
from simz1_osm_turn_audit import load_lanes, load_xml

OUT = ROOT/'scenarios/zona1/od/balanced-gateway-v1'
COPY = OUT/'access-review-v2'
HERE = COPY/'osm-evidence'
RESULTS = ROOT/'runtime/correction7'
A, V, B, C, D = ('osm_1273145789_0_forward', 'osm_1270930401_0_forward',
    'osm_1273145790_0_forward', 'osm_734011349_14_forward', 'osm_260940553_0_forward')

# Reviewed Task 2 / C529-A / C529-B / C529-C / C529-D replacements, not exclusions. Keep the historical capture
# untouched; neither these values nor the baseline are renewed by a test run.
# This file and both Java sources are covered by the existing fingerprint().
REVIEWED_SOURCE_EXPECTATIONS = {
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1AdmissionConfigGroup.java': dict(
        historical_sha256='7f183a3e1147de0e3a8740e445845c4bad511015153efcf8cde195f4048921e5',
        expected_sha256='53ed7ae028dde48e08b6e3212e2f18b0841c029b31b9196f36e1fad1b0ecf777',
        reason='Explicit origin-policy variant with legacy default. Reject unknown policy and incompatible strict/whole-body/queue/FIFO/thread/removal settings; no capacity, signal or demand changes.',
        reference='docs/SIMZ1_180000_AVANCE.md',
        coverage=('SimZ1OriginPolicyCheck','test_simz1_origin_policy_contract'),
        evidence='runtime/diagnostics/run110k-implementation-phase8-20261106/policy-components-attempt2.json'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1Configuration.java': dict(
        historical_sha256='95346a3c056f4d6e7928a1353fc0b2c51c5454d15374c3c373d2e1de69ead1b6',
        expected_sha256='c833af5eb1454aac2603393ca3558a2be301282f069a6f5dadbf82e2eec8a0f3',
        reason='Validate the explicit origin-policy requirements before QSim; existing configuration guards remain intact.',
        reference='docs/SIMZ1_180000_AVANCE.md',
        coverage=('SimZ1OriginPolicyCheck','test_simz1_origin_policy_contract'),
        evidence='runtime/diagnostics/run110k-implementation-phase8-20261106/native-design-review.json'),
    'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QueueWithBuffer.java': dict(
        historical_sha256='42bf532a1c118dfdaa4392713c86810610fe01ad4cfb46cc08e8b5f4efc0423d',
        expected_sha256='7c870b60bab148eef4fb7b930a8419ce6c8d5896bd3b7f6e076575203a95f32c',
        freight_entry_previous_sha256='d4b6d8a1f64a8fca06c379d7e935bd1b5fb1d242394ade1c0a48c1d068f4e17f',
        freight_entry_review='Run55K proved native activity admission lacked assigned-window authorization before poll/reservation. Preserve v1; explicit user-authorized v2 permits entry only through close+3600 inclusive, never extends completion, moves or removes expired FIFO heads.',
        freight_entry_evidence='runtime/diagnostics/run55k-freight-failure-20261108/: baseline-native.json (12 failures), corrected-native.json (42 PASS); auditor, duplicate/late/expiry negatives and protected mutation/absence controls.',
        origin_review_previous_sha256='a1bbdb596b3b3ff5013094c6f75c7776a72d236d34cfe25085b714646f2929ef',
        origin_review='Dispatch explicit origin policy after unchanged native flow gate; preserve activity-buffer storage, one native debit, shared FIFO and every transit/upstream path.',
        origin_evidence='runtime/diagnostics/run110k-implementation-phase8-20261106/: baseline-mechanisms.json, legacy-mechanisms-attempt2.json, gap-mechanisms-attempt2.json, policy-components-attempt2.json, gap-six-qsim-attempt2, gap-day-qsim-attempt3.',
        blocking_stop_review_previous_sha256='a10484abe47082b67fdf4283c4e4f637d32d1600f102bbb9885dfdf4d2709f92',
        blocking_stop_review='Keep a current-link blocking transit stop as a FIFO barrier in both independent travelling-slot scans. The eligible bus itself may be selected; later actors cannot be buffered before its dwell. Native stop lifecycle, flow debt, reception and body reservations remain authoritative.',
        blocking_stop_evidence='runtime/diagnostics/run10k-blocking-stop-20261105/: before-blocking.log FAIL1, before-nonblocking.log PASS0, final-blocking.log PASS0; original historical capture still rejected. SimZ1BlockingStopCheck includes dwell+1, nonblocking, postdeparture and eligible-bus controls.',
        discharge_review_previous_sha256='b77fc6b0a5b00de500913c98f8349550b1d383a9690e0559edbb34054e12fd66',
        discharge_review='Select a ready independent travelling slot behind a retained native buffer grant without changing FIFO, reservations or flow debt; restore travelling PCU on native transit stop reinsertion to match removal.',
        discharge_evidence='runtime/diagnostics/discharge-20261103/: travel-before2.log, travel-after.log, arrivals-before/evidence.json, arrivals-after/evidence.json, protected-review-before-update.log; native component and Controller fixtures, no scale run.',
        previous_reviewed_sha256='8babb4b7acc7525eb8af2ace04cc3cd86a8d5f6c3da543904ff4504587ce72ca',
        arrival_review='Reject premature native arrival while modeled front is held behind earlier bodies; retain independent physical-slot discharge, flow debt and transit stop lifecycle before querying arrival.',
        arrival_evidence='SimZ1ArrivalClearanceCheck; runtime/l18-local-20261102/arrival-before-3.log; arrival-transit-regressions.json',
        reason='Extract unchanged floor/debt/two-step formula to shared SimZ1PassageTiming; no admission or timing relaxation.',
        reference='docs/SIMZ1_180000_AVANCE.md',
        coverage=('SimZ1TemporalRouteCheck', 'SimZ1TemporalInstallationCheck', 'Zona1SignalGreenWindowCheck', 'SimZ1ArrivalClearanceCheck'),
        evidence='python/test_simz1_temporal_passage.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/Zona1SignalGreenWindow.java': dict(
        historical_sha256='8e24f653a5acc7197d7ec31edde5d616bdbfb370b08e1a094d893fd640ae790e',
        expected_sha256='0b6df6449c1c32c93bceebfd2dbd73feaf443ea0c0b3aa830fb238d3e007aabe',
        reason='Complete bounded common-period tri-state query across distinct controllers; native source amber and connector deadlines; effective-phase cache key.',
        reference='docs/SIMZ1_180000_AVANCE.md',
        coverage=('SimZ1TemporalRouteCheck', 'SimZ1TemporalInstallationCheck', 'Zona1SignalGreenWindowCheck'),
        evidence='python/test_simz1_temporal_passage.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1RouteSafety.java': dict(
        historical_sha256='6905c60cd2217f5786d4e0a64e06c7a90e3d141d0c3d8dbd4314f048344d4d1b',
        expected_sha256='f6799dc429d6d2f0c4452ece4307a7d560c58820ca95b3f333e8f0d8dc9b5d4e',
        previous_reviewed_sha256='8fd9fd327cfcb9b3643dd35667f4ed80c2caa54c2e0886ad9820623afef881fe',
        temporal_review='Temporal effective geometry and vehicle-type lookup; existing OD/OSM replacement checks retained.',
        temporal_evidence='python/test_simz1_temporal_passage.py',
        reason='C529-B (retains Correction 7): Validate replacement against the selected private trip after existing prefix, destination, OSM and lane checks.',
        reference='docs/C529_B_CONTRATO_OD_NATIVO.md',
        coverage=('SimZ1OdContractCheck', 'SimZ1OdReservationsCheck', 'Restriction17478998Probe', 'RouteSafetyCheck'),
        evidence='python/test_simz1_native_od.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1TurnRouter.java': dict(
        historical_sha256='b4f9a6d42180c9ec82c3b82108831bfa9911b39177246b599c6e9ae4a0607a89',
        expected_sha256='15716de0e4ca81b4e2a3ed814a05bee639ec7f448e3e44cdd8ece7e969048379',
        previous_reviewed_sha256='a0ad00032bba688df493ab27efc0d2aa7ba7b7f2d71372b01a0b97ff5f05d43e',
        temporal_review='Search also retains pending physical passage; does not globally remove turns; original OD/OSM product retained.',
        temporal_evidence='python/test_simz1_temporal_passage.py',
        reason='C529-B (retains Correction 7): Search the product of existing OSM DFA and per-trip OD progress; keep continuous native occurrence prefix.',
        reference='docs/C529_B_CONTRATO_OD_NATIVO.md',
        coverage=('SimZ1OdContractCheck', 'SimZ1OdReservationsCheck', 'Restriction17478998Probe', 'RouteSafetyCheck'),
        evidence='python/test_simz1_native_od.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/CongestionAwareRerouting.java': dict(
        historical_sha256='215a2dc7580141477fb9d963aab1f1727d7022ae65f599cfad6898b4dc32b6f6',
        expected_sha256='22ebe187eaa2263e2e8fb71a14594875c1fc9372e922dc2143932c7301991857',
        day_review_previous_sha256='df5515325c36cd3f405f8f5c942a725bb11e21863fa08faf524b125eb3fdce18',
        day_review='Monotonic exclusive phase instrumentation; production decisions, budget, cadence, order, cursor, physical validation and reservations unchanged.',
        day_evidence='runtime/diagnostics/repair24h-20261103/',
        previous_reviewed_sha256='063465c290bc0eba15fa5637d4e1425b4e44a8b5c499417c1c64851dd96cb13b',
        temporal_review='Proved impossible-route trigger and compatible repair in the sole attempt installer; strict cost improvement otherwise; C/D accumulation untouched.',
        temporal_evidence='python/test_simz1_temporal_passage.py',
        reason='C529-D retains C529-A/B/C: explicit accumulated physical intervals across observed signal pauses; unchanged costs and thresholds; one production installer exercised with native body reservations and private OD.',
        reference='docs/C529_D_RETENCION_ENTRE_FASES.md',
        coverage=('SimZ1RetentionPhaseCheck', 'SimZ1RetentionLifecycleCheck', 'SimZ1RetentionInstallationCheck', 'SimZ1RetentionBeforeCheck', 'SimZ1RetentionCheck', 'SimZ1OdContractCheck', 'SimZ1OdReservationsCheck', 'Restriction17478998Probe', 'RouteSafetyCheck'),
        evidence='python/test_simz1_retention_phases.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/ExperiencedTimeRouting.java': dict(
        historical_sha256='58920c0825de7441cf7f8ad0c212e8a14cd2a63e48927d392e630b8400347a7b',
        expected_sha256='306b31c420126d5c66fe4f920a8519fd8e77ead61f12753ddc6874f54a2eb328',
        reason='C529-B (retains Correction 7): Carry existing leg trip ID into native request attributes and resolve the actual ReRoute trip, including cloned plans.',
        reference='docs/C529_B_CONTRATO_OD_NATIVO.md',
        coverage=('SimZ1OdContractCheck', 'SimZ1OdReservationsCheck', 'Restriction17478998Probe', 'RouteSafetyCheck'),
        evidence='python/test_simz1_native_od.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/UnsignalizedPriority.java': dict(
        historical_sha256='253a76f88fba3a288058182f3cf664edf0aa077d7f1459d6135e58235d2aba06',
        expected_sha256='eae808c7a519fa7b187453886c4eeea85b3837501c4e4921389ca1ed62da785b',
        reason='C529-A: expose all actual future-passage priority blockers and existing head stop readiness; preserve physical canCompete.',
        reference='docs/C529_A_VETO_ENTRE_PASAJES.md',
        coverage=('SimZ1PassageCycleCheck', 'SimZ1PassageFairnessCheck', 'SimZ1PriorityReceiverCheck', 'SimZ1PriorityLookaheadCheck'),
        evidence='python/test_simz1_passage_cycle.py'),
    'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/Zona1QNodeImpl.java': dict(
        historical_sha256='f2cc41d059257c66722fbef7438544185fbc2c044d9f00bf5af5c4a198aab749',
        expected_sha256='46a98fc63dadedaa4077d36f3173bdb079ca11054d558a2b9a63f1e39a9c8272',
        attribution_previous_sha256='fd49d278a9d61fd30048a14f25ffe3fd0db1106239c2af9192ab173bdb85147b',
        attribution_review='Capture the single native receiver query result and pass it to diagnostics after the unchanged short-circuit body admission. No new query, physical decision, movement, capacity or reservation change.',
        attribution_evidence='runtime/diagnostics/phases123-20261104/native/attribution-strict-results.json; SimZ1AdmissionAttributionCheck: native/body/both refusals and actual admission, before 1/after 0; protected mutation/absence controls.',
        pre_arbitration_reviewed_sha256='a1785d5cb1edbc0e91a2f62306ce8cc2aedd03f372671fd14e1cfe94fddaeccf',
        arbitration_review='Order real parallel lane heads by existing native head age; refresh after successful pop and skip rejected heads. No changes to turn, reception, crossing clearance, priority across approaches, physical dimensions or flow debt.',
        arbitration_evidence='runtime/2avenida-20261102/arbitration-before.log (exit 1); arbitration-after-5.log (exit 0); SimZ1LaneHeadArbitrationCheck',
        reason='C529-A: distinguish physical/crossing/lane/signal rejection from priority dependencies; verify real offered heads.',
        reference='docs/C529_A_VETO_ENTRE_PASAJES.md',
        coverage=('SimZ1PassageCycleCheck', 'SimZ1DownstreamStorageCheck', 'SimZ1TenthStreetReceptionCheck', 'SimZ1LaneHeadArbitrationCheck'),
        evidence='python/test_simz1_passage_cycle.py'),
    'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1CorridorOccupancy.java': dict(
        historical_sha256='a8a3c23a6db8c0c26ecc6e786b1af3c2898a0e545a2b03a16137485ab50b4f14',
        expected_sha256='b93519771814dfaef14b3c6c9d15eb3b47f0cf950db39a1d15c3f7b9760f908d',
        origin_review_previous_sha256='9aeb7579ffdfcc2e9cee33ccbe0cc32cf8481877427aa3bb1c7eb4ed1e69266e',
        origin_review='Opt-in M1/M2/M5 at fixed native buffer anchor; verify full body, actual original-terminal connections and route reach, retain all older-body order/locks and invalidate stale staging before commit. Legacy activity unchanged; committed anchor retained against rerouting.',
        origin_evidence='runtime/diagnostics/run110k-implementation-phase8-20261106/: native-design-review.json, policy-components-attempt2.json; native before/after and QSim6/10 with unchanged negative controls. No massive acceptance.',
        pre_arrival_reviewed_sha256='e6a5ee015efc91f7db89813d489aee082c6877cf5225fbbea6c7779d1f70c6ed',
        arrival_review='Pure native endpoint comparison against existing modeled front; no movement, reservation release, capacity, dimensions or auditor change.',
        arrival_evidence='SimZ1ArrivalClearanceCheck; runtime/l18-local-20261102/freight-000155-failure.json',
        previous_reviewed_sha256='4d573bdd16fd963d6235f80b28e834ed0636231b6867c3cd649dc5a6c286050a',
        temporal_review='Read-only temporal geometry reuses routeReach and body clearance; replacement rejects complete-period impossibility; C529-A admission and reservations retained.',
        temporal_evidence='python/test_simz1_temporal_passage.py',
        reason='C529-A: deterministic oldest-head choice only for closed future-priority cycles sharing a node footprint; revalidate and retain body locks.',
        reference='docs/C529_A_VETO_ENTRE_PASAJES.md',
        coverage=('SimZ1PassageCycleCheck', 'SimZ1PassageAffectedChecks', 'SimZ1TransitPassageReleaseCheck', 'SimZ1TransitPassageNativeCheck', 'SimZ1ArrivalClearanceCheck'),
        evidence='python/test_simz1_passage_cycle.py'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1FailureReport.java': dict(
        historical_sha256='00954a86207d6d3a42e44c5356101498eebc17978b3a56fdc6adb9482362c777',
        expected_sha256='8c5aca71cf44fdf77a48cb2cd46ee96cf4fff6350bb175287b51bf3694166a1c',
        reason='Task 2: distinguish propagated causes, suppressed/injector branches and block completion.',
        reference='docs/CIERRE_CARGA_Y_CAUSA_PRIMARIA_SIMZ1.md',
        coverage=('SimZ1FailureReportCheck', 'NativeCleanupTests.test_failure_report_roundtrip_extractor',
                  'CausalDiagnosticTests'),
        evidence='runtime/failure-cleanup-632wnuky/focused-results.json'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1Freight.java': dict(
        historical_sha256='5de26967ad3a8eee80ca7d45d42c16ab9e634d8dc56ebc9cce844005dd03219c',
        expected_sha256='c36aa310533860c2f8de61757099c0c156ec4dfe1cc7a6368f3ac91d601428e6',
        freight_entry_previous_sha256='2128b75cf373d0f718db24ce9af77831683929ebf0b6ba8ecdc603a6bbd53767',
        freight_entry_review='Run55K proved native activity admission lacked assigned-window authorization before poll/reservation. Preserve v1; explicit user-authorized v2 permits entry only through close+3600 inclusive, never extends completion, moves or removes expired FIFO heads.',
        freight_entry_evidence='runtime/diagnostics/run55k-freight-failure-20261108/: baseline-native.json (12 failures), corrected-native.json (42 PASS); auditor, duplicate/late/expiry negatives and protected mutation/absence controls.',
        day_review_previous_sha256='bd1834b4b8f87e7b312db67ec52179aedf4722933a36d83976e12bba7188f765',
        day_review='Fixed-day pending acceptance requires the native pre-cleanup census; real arrival/body/window guards and requireApproved remain.',
        day_evidence='runtime/diagnostics/repair24h-20261103/',
        reason='Authorized freight-close-plus3600-v1: original entry windows, native clearance and completion preserved; excess is experimental review, historical policy unchanged.',
        reference='docs/CIERRE_CARGA_Y_CAUSA_PRIMARIA_SIMZ1.md',
        coverage=('SimZ1FreightClosureCheck','SimZ1FreightCompletionCheck',
                  'NativeCleanupTests.test_closure_component_parallel_manager_no_simulation'),
        evidence='runtime/closure-20261102/freight-completion-java.log'),
    'src/main/java/gt/edu/uvg/sim/zona1/RunZona1Simulation.java': dict(
        historical_sha256='a1f276b6bd4fcacb3a6173d5e70da60d0553a040a016c24f84de72624f06a76f',
        expected_sha256='4cd9582681273a0b0f8ed62723bc9735c82b99afe830e3088f44ac8881f3e9f2',
        reason='Record native ProcessHandle identity atomically before loading and install explicitly selected fixed-day observer.',
        reference='docs/RUNBOOK_MANUAL_24H.md',
        coverage=('SimZ1ProcessIdentityCheck', 'SimZ1ArrivalClearanceCheck'),
        evidence='runtime/diagnostics/repair24h-20261103/'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1.java': dict(
        historical_sha256='67c644c905127887ed3b10b818bdf5173c06063743c14490b9ec7435253fcc17',
        expected_sha256='8dcab4bc6b2059c9f670b42ac318a1b6f194835d77c35be029ca83b3fc9e27e8',
        reason='Install fixed-day observer only when the selected configuration declares the versioned policy.',
        reference='docs/RUNBOOK_MANUAL_24H.md',
        coverage=('SimZ1DayObservationCheck', 'SimZ1DayTransitCheck'),
        evidence='runtime/diagnostics/repair24h-20261103/'),
    'src/main/java/gt/edu/uvg/sim/zona1/TripTableExporter.java': dict(
        historical_sha256='6fd0335444d36a2e70f4c8a5f4a74fc0e2573ccca126e51abb10e132d26dc886',
        expected_sha256='c245c9dadd4ee706aa62fcedb73fc17728a19470eae6e772039be8bf75a0b2bd',
        reason='Use declared fixed-day horizon and pre-cleanup marker to distinguish administrative censoring from real aborts; historical behavior preserved.',
        reference='docs/RUNBOOK_MANUAL_24H.md',
        coverage=('SimZ1ArrivalClearanceCheck', 'test_simz1_day_observation'),
        evidence='runtime/diagnostics/repair24h-20261103/'),
    'src/main/java/gt/edu/uvg/sim/zona1/SimZ1Diagnostics.java': dict(
        historical_sha256='98251bda980f118fae755f7b269190b2d6f0e75953e529940d10d2293172132f',
        expected_sha256='844ccf710f01740e0a5cf9097808d2fde8a5fe52002a9e319f8c4b829f2e36d9',
        reason='Observe callback thread by identity with complete bounded-frequency explicit stacks and separate raw WAIT attempts/vehicles/age gauges.',
        reference='docs/RUNBOOK_MANUAL_24H.md',
        coverage=('SimZ1DiagnosticsPhaseCheck', 'test_simz1_performance_observations'),
        evidence='runtime/diagnostics/repair24h-20261103/'),
    'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/Zona1NativeDiagnostics.java': dict(
        historical_sha256='2ed48b64d09a4037f3052410873c40a5866882cff408df395a1fc568a1629369',
        expected_sha256='17e820cfa79b9fd527f417b302db9b2c0391843713c0afef9e6720046c763b01',
        attribution_previous_sha256='4df30a1733876719a8d9a6317fc354b845d9689c5debef5ae90b2efaddf55073',
        attribution_review='Version the separate native/body rejection evidence while retaining combined storage_wait rejection and non-atomic snapshots. Count the accepting terminal using its captured native result; short-circuited body admission remains unobserved.',
        attribution_evidence='runtime/diagnostics/phases123-20261104/native/attribution-strict-results.json and attribution-native-event-records.json; contract/attribution-native-python-reconciliation.json: six native events, eighteen rejected safety mutations; no auditor relaxation.',
        reason='Versioned exhaustive wait categorization includes receiver_storage_or_terminal_slot and explicit unknown fallback; raw reasons and physics retained.',
        reference='docs/RUNBOOK_MANUAL_24H.md',
        coverage=('SimZ1DiagnosticsPhaseCheck', 'test_simz1_performance_observations'),
        evidence='runtime/diagnostics/repair24h-20261103/'),
}
VALIDATE_RECEIPT = 'runtime/workflow/validated-balanced-gateway-v1.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt_snapshot(root):
    """Preservation state, never an approval: first Validate may start without one."""
    path=Path(root)/VALIDATE_RECEIPT
    if not path.exists():return None
    if not path.is_file():raise ValueError('Validate receipt path is not a file')
    return sha(path)


def check_protected_sources(root, baseline, receipt_start_sha):
    """Read-only check of every protected entry, with explicit reviewed replacements."""
    expected={path.replace('\\','/'):value for path,value in baseline.items()}
    # C529-B replaces the four prior Java exclusions with exact reviewed hashes.
    # Retain the pre-existing Python/workflow exceptions; do not widen their scope.
    authorized={'python/'+name+'.py' for name in ('simz1_balanced_od','simz1_od_policy',
        'simz1_osm_turn_audit','generate_montecarlo_z1','simz1_balanced_od_audit','simz1_workflow_state')}
    authorized.add('scripts/simz1_workflow.ps1')
    errors=[]
    for path,review in REVIEWED_SOURCE_EXPECTATIONS.items():
        if expected.get(path)!=review['historical_sha256']:
            errors.append(f'{path}: replaced historical hash does not match original baseline')
        if path in authorized:
            errors.append(f'{path}: reviewed source must not be excluded')
        expected[path]=review['expected_sha256']
    # Preserve its exact initial state, including absence before first Validate.
    # This is an anti-write check, not a prerequisite approval for the validator.
    # Do not copy/write/renew a receipt to satisfy a test.
    expected[VALIDATE_RECEIPT]=receipt_start_sha
    checked=0
    for path,value in expected.items():
        if path in authorized:continue
        checked+=1
        source=Path(root)/path
        if path==VALIDATE_RECEIPT and value is None:
            if source.exists():errors.append(f'{path}: receipt appeared after initially absent state')
        elif not source.is_file():
            errors.append(f'{path}: expected file absent')
        elif (actual:=sha(source))!=value:
            errors.append(f'{path}: SHA256 {actual} != expected {value}')
    if errors:raise AssertionError('\n'.join(errors))
    return checked


def tiny_graph():
    """Search fixture using the production model, not another generator."""
    graph = BalancedGatewayModel.__new__(BalancedGatewayModel)
    graph.sequences = SequenceContract()
    edges = [(A,'a','j',10),(C,'c','j',36),(V,'j','v',9.5),(B,'v','m',70),
             (D,'v','m',200),('E','m','end',20),('X','root','a',10),('H','a','c',36),('R','m','a',200)]
    graph.links = {k:dict(from_node=a,to_node=b,length=length,freespeed=10.) for k,a,b,length in edges}
    graph.classification = dict.fromkeys(graph.links,'interior')
    graph.successors = {k:sorted(t for t,r in graph.links.items() if r['from_node']==l['to_node'])
                        for k,l in graph.links.items()}
    graph.lane_movements = graph.successors
    graph.entry_gateways, graph.exit_gateways = {}, {}
    return graph


class SequenceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt_start_sha=receipt_snapshot(ROOT)
        cls.doc = load_contract()
        cls.osm = load_xml(COPY/'map.osm')
        cls.links = {r.get('id'):r for r in load_xml(COPY/'network.xml').findall('links/link')}
        cls.moves = load_lanes(COPY/'lanes.xml')
        cls.model = load_model(COPY/'network.xml', OUT/'perimeter.geojson', COPY/'lanes.xml', COPY/'map.osm', OUT/'access.json')
        cls.report = dict(status='NOT_YET_PASSED', contract_sha256=SHA256,
            controller_started=False, qsim_started=False, validate_executed=False,
            dry_run_executed=False, massive_generation_executed=False)

    def test_01_forbidden_and_legal_sequences_all_modes(self):
        for mode in ('car','bus'):
            contract = SequenceContract(self.doc, mode)
            with self.assertRaisesRegex(ValueError,'occurrence 2'): contract.validate([A,V,B])
            contract.validate([C,V,B]); contract.validate([A,V,D]); contract.validate([V])
        for path in ([C,V,B],[A,V,D]):
            self.assertTrue(all(b in self.moves[a] for a,b in zip(path,path[1:])))

    def test_02_search_alternative_and_distinct_arrivals(self):
        graph = tiny_graph()
        self.assertEqual(graph.route(A,'E'),[A,V,D,'E'])
        self.assertEqual(graph.route(C,'E'),[C,V,B,'E'])
        self.assertEqual(graph.route('X','E'),['X','H',C,V,B,'E'])
        graph.validate_route(graph.route(A,'E'))
        # A cheaper reset-state arrival through V must not hide an alternative
        # that reaches the same link without V and can still legally use it.
        graph=tiny_graph()
        graph.links['H'].update(from_node='j',to_node='v',length=1000.)
        graph.links['R'].update(to_node='j')
        graph.successors={A:[V,'H'],V:[B,D],'H':[D],D:['R'],'R':[V],B:['E'],'E':[],C:[V],'X':[A]}
        graph.lane_movements=graph.successors
        self.assertEqual(graph.route(A,'E'),[A,'H',D,'R',V,B,'E'])

    def test_03_prefix_and_exit_chain_boundaries(self):
        graph = tiny_graph()
        graph.entry_gateways[A] = dict(observation_link=V, link_ids=[A,V])
        self.assertEqual(graph.route(A,'E'),[A,V,D,'E'])
        graph = tiny_graph()
        graph.exit_gateways['E'] = dict(observation_link=V, link_ids=[V,B,'E'])
        self.assertEqual(graph.route('X','E'),['X','H',C,V,B,'E'])
        with self.assertRaisesRegex(ValueError,'Inaccessible'): graph.route(A,'E')

    def test_04_no_alternative_no_circular_escape(self):
        graph = tiny_graph()
        graph.entry_gateways[A] = dict(observation_link=V,link_ids=[A,V])
        graph.successors[V] = [B,'Q']
        graph.links['Q'] = dict(from_node='v',to_node='c',length=10.,freespeed=10.)
        graph.classification['Q']='interior'; graph.successors['Q']=[C]
        with self.assertRaisesRegex(ValueError,'Inaccessible'): graph.route(A,'E')

    def test_05_repeated_occurrences_and_single_link(self):
        graph = tiny_graph()
        graph.validate_route([C,V,B,'R',A,V,D,'E'])
        with self.assertRaisesRegex(ValueError,'occurrence 6'): graph.validate_route([C,V,B,'R',A,V,B,'E'])
        self.assertEqual(graph.route(V,V),[V])
        with self.assertRaisesRegex(ValueError,'Disconnected'): graph.validate_route([A,B])

    def test_06_production_guard_closes_both_only_with_verified_evidence(self):
        result = validate_osm_turns(COPY/'map.osm',COPY/'network.xml',COPY/'lanes.xml')
        rows = {r['relation_id']:r for r in result['relations']}
        self.assertEqual(rows['17478998']['status'],'enforced_by_shared_sequence_contract')
        self.assertEqual(rows['17884471']['status'],'MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER')
        self.assertFalse(rows['17884471']['unrestricted_access_verified'])
        self.report['osm_guard'] = result

    def test_07_malformed_exact_identity_and_warning(self):
        row=self.osm.find("relation[@id='17884471']")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always'); result=malformed_disposition(row)
        self.assertTrue(any('MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER' in str(w.message) for w in caught))
        self.assertEqual(result['relation']['members'],[dict(type='way',ref='34993910',role='to')])
        self.assertFalse(result['source_repair_applied']); self.assertFalse(result['global_target_ban'])
        history=load_xml(HERE/'relation-17884471-history.osm').findall('relation')
        self.assertEqual([r.get('version') for r in history],['1','2'])
        self.assertEqual(relation_identity(history[-1]),relation_identity(row))
        deleted=load_xml(HERE/'way-381158225-history.osm').findall('way')[-1]
        self.assertEqual((deleted.get('version'),deleted.get('visible'),deleted.get('changeset')),('11','false','178612606'))
        self.report['malformed_treatment'] = result

    def test_08_version_members_tags_and_identity_mutations_block(self):
        original=self.osm.find("relation[@id='17884471']")
        mutations=[]
        for key,value in [('id','999'),('version','3'),('changeset','999'),('timestamp','2026-01-01'),('visible','false'),('uid','0')]:
            row=copy.deepcopy(original); row.set(key,value); mutations.append(row)
        row=copy.deepcopy(original);ET.SubElement(row,'member',type='way',ref='381158225',role='from');mutations.append(row)
        row=copy.deepcopy(original);row.find('tag').set('v','no_left_turn');mutations.append(row)
        for row in mutations:
            with self.subTest(identity=row.attrib),self.assertRaises(ValueError): malformed_disposition(row)

    def test_09_contract_and_each_source_hash_mutation_block(self):
        with tempfile.TemporaryDirectory(prefix='simz1-sequence-hashes-') as folder:
            root=Path(folder)
            for name in self.doc['sources']:
                dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
            for name in self.doc['sources']:
                dest=root/name;raw=dest.read_bytes();dest.write_bytes(raw+b'\n')
                with self.subTest(source=name),self.assertRaisesRegex(ValueError,'hash mismatch'):
                    load_contract(source_root=root)
                dest.write_bytes(raw)
            altered=root/'contract.json';altered.write_bytes(CONTRACT.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'contract SHA256'):load_contract(altered,root)

    def test_10_other_incomplete_record_is_not_exempt(self):
        osm=copy.deepcopy(self.osm);row=osm.find("relation[@id='17884471']");row.set('id','999999999')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'map.osm';ET.ElementTree(osm).write(path,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'source evidence hash mismatch'):validate_osm_turns(path,COPY/'network.xml',COPY/'lanes.xml')
        # Generic incomplete relations are still rejected on an unpinned tiny graph.
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/'map.osm').write_text('<osm><way id="w"/><relation id="999"><member type="way" ref="w" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation></osm>')
            (folder/'network.xml').write_text('<network><nodes><node id="a"/><node id="b"/></nodes><links><link id="l" from="a" to="b" origid="w" modes="car"/></links></network>')
            (folder/'lanes.xml').write_text('<laneDefinitions/>')
            with self.assertRaisesRegex(ValueError,'999'):validate_osm_turns(folder/'map.osm',folder/'network.xml',folder/'lanes.xml')

    def test_11_ten_pair_corrections_and_unfixed_pair_still_block(self):
        resolution=json.loads((OUT/'osm-turn-resolution.json').read_bytes())
        self.assertEqual(len(resolution['changes']),10)
        self.assertEqual(sum(r['removed_targets'] for r in resolution['changes']),22)
        contract=SequenceContract(self.doc)
        for row in resolution['changes']:
            self.assertNotIn(row['to_link'],self.moves[row['from_link']])
            with self.assertRaises(ValueError):contract.validate([row['from_link'],row['to_link']])
        with self.assertRaisesRegex(ValueError,'6008781'):
            validate_osm_turns(COPY/'map.osm',COPY/'network.xml',ROOT/'scenarios/zona1/lanes.xml')

    def test_12_all_existing_115_private_pairs_full_routes(self):
        count=0
        for row in json.loads((OUT/'access-review.json').read_bytes())['entry_exit_pairs']:
            if row['status']=='static_shortest_path_admissible':
                self.model.validate_route(self.model.route(row['entry'],row['exit']));count+=1
        self.assertEqual(count,115);self.report['existing_private_pairs_checked']=count

    def test_13_existing_generator_99_trips_four_classes_and_same_times(self):
        from test_simz1_balanced_gateway_od import SmallGenerationTests, SEED
        from simz1_agent_types import load_catalog,sample_departures
        catalog=load_catalog(ROOT/'scenarios/zona1/agent-types-balanced-v1.json')
        with tempfile.TemporaryDirectory() as folder:
            people,report=SmallGenerationTests().generate(Path(folder),self.model)
        self.assertEqual(len(people),99)
        for person in people:
            route=person.find('plan/leg/route')
            self.model.validate_route((route.text or '').split())
            kind=person.findtext("attributes/attribute[@name='simz1AgentType']")
            self.assertEqual(float(person.find('plan/activity').get('end_time')),
                             sample_departures(kind,1,SEED,person.get('id'),catalog)[0])
        self.assertEqual(set(report['balanced_od_audit']['private_class_counts']),set(CLASS_BY_TYPE.values()))
        self.report['bounded_generated_private_trips_checked']=99

    def test_14_fixed_freight_buses_and_l12_l13_unchanged(self):
        contract=SequenceContract(self.doc)
        freight=json.loads((COPY/'freight/routes.json').read_bytes())
        self.assertEqual(len(freight['routes']),4)
        for row in freight['routes']:
            path=row['link_ids'];contract.validate(path)
            for a,b in zip(path,path[1:]):
                self.assertEqual(self.links[a].get('to'),self.links[b].get('from'))
                if a in self.moves:self.assertIn(b,self.moves[a])
        original=json.loads((ROOT/'scenarios/zona1/freight/weekday-compact-v3/routes.json').read_bytes())
        self.assertEqual(freight['routes'],original['routes'])
        bundle=json.loads((ROOT/'scenarios/zona1/transit/weekday-v2/route-bundle.json').read_bytes())
        extra={l['id']:l for l in bundle['additional_links']}; links={**self.links,**extra}
        count=0; users=set()
        for service in bundle['services']:
            for part in service['parts']:
                path=part['link_ids'];contract.validate(path);count+=1
                for a,b in zip(path,path[1:]):
                    self.assertEqual(links[a].get('to'),links[b].get('from'))
                    if a in self.moves and b not in self.moves[a]:self.assertEqual(extra[b]['modes'],'bus')
                if 'osm_34993910_0_forward' in path:users.add(service['service_id'])
        self.assertEqual(count,24);self.assertEqual(users,{'transmetro_L12','transmetro_L13'})
        self.report.update(freight_routes_checked=4,transit_parts_checked=24,l12_l13_target_preserved=True)

    def test_15_protected_sources_physics_composition_receipt(self):
        baseline=json.loads((HERE/'preserved-input-hashes.json').read_bytes())['sha256']
        checked=check_protected_sources(ROOT,baseline,self.receipt_start_sha)
        from simz1_agent_types import load_catalog
        from simz1_demand_composition import split
        composition=split(180000,load_catalog(ROOT/'scenarios/zona1/agent-types-balanced-v1.json'))
        self.assertEqual(composition['private_vehicles'],178200);self.assertEqual(composition['freight_vehicles'],1800)
        self.assertEqual(composition['family_counts'],dict(carro=79200,moto=99000,pesado=1800))
        shares=named_percentages(json.loads((OUT/'mix.json').read_bytes()))
        counts={k:178200*v/sum(shares.values()) for k,v in shares.items()}
        self.assertEqual({CLASS_BY_TYPE[k]:v for k,v in counts.items()},dict(EXTERNAL_EXTERNAL_THROUGH=89100,
            EXTERNAL_INTERNAL=35640,INTERNAL_EXTERNAL=35640,INTERNAL_INTERNAL=17820))
        self.report['preserved_previous_evidence_hashes']=checked
        self.report['unchanged_starting_validate_receipt_sha256']=self.receipt_start_sha
        self.report['starting_validate_receipt_state']='absent' if self.receipt_start_sha is None else 'present'

    def test_16_java_probe_and_standard_reroute_no_simulation(self):
        java=Path(r'C:\Program Files\Java\jdk-17\bin')
        classpath=str(ROOT/'target/classes')+os.pathsep+(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()
        names=('SimZ1SequenceContract','SimZ1TripOd','SimZ1RouteSafety','SimZ1TurnRouter','CongestionAwareRerouting','ExperiencedTimeRouting','DrivingProfiles','SimZ1ActiveRetention')
        sources=[ROOT/f'src/main/java/gt/edu/uvg/sim/zona1/{name}.java' for name in names]
        existing_checks=('RouteSafetyCheck','FastestTimeRoutingCheck','GatewayRouteSafetyCheck')
        check_sources=[ROOT/f'src/test/java/gt/edu/uvg/sim/zona1/{name}.java' for name in existing_checks]
        RESULTS.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='simz1-sequence-java-') as folder:
            empty=Path(folder)/'empty';empty.mkdir()
            run=subprocess.run([str(java/'javac.exe'),'-encoding','UTF-8','-proc:none','-cp',classpath,
                '-sourcepath',str(empty),'-d',folder,*map(str,sources),*map(str,check_sources),str(HERE/'Restriction17478998Probe.java')],
                cwd=ROOT,capture_output=True,text=True,timeout=60)
            (RESULTS/'java-compile.log').write_text(run.stdout+run.stderr,encoding='utf-8')
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            run=subprocess.run([str(java/'java.exe'),'-cp',os.pathsep.join([folder,str(ROOT/'src/main/resources'),classpath]),
                'gt.edu.uvg.sim.zona1.Restriction17478998Probe'],cwd=ROOT,capture_output=True,text=True,timeout=60)
            (RESULTS/'java-probe.log').write_text(run.stdout+run.stderr,encoding='utf-8')
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            probe_output=run.stdout
            for name in existing_checks:
                regression=subprocess.run([str(java/'java.exe'),'-cp',os.pathsep.join([folder,str(ROOT/'src/main/resources'),classpath]),
                    'gt.edu.uvg.sim.zona1.'+name],cwd=ROOT,capture_output=True,text=True,timeout=60)
                (RESULTS/(name+'.log')).write_text(regression.stdout+regression.stderr,encoding='utf-8')
                self.assertEqual(regression.returncode,0,regression.stdout+regression.stderr)
        data=json.loads(next(line.split('=',1)[1] for line in probe_output.splitlines() if line.startswith('OSM_PROBE=')))
        self.assertEqual(data['status'],'PASS');self.assertFalse(data['controller_started']);self.assertFalse(data['qsim_started'])
        self.report['java_regression']=data
        self.report['existing_java_routing_regressions_passed']=list(existing_checks)
        self.report['java_source_sha256']={p.relative_to(ROOT).as_posix():sha(p) for p in sources}


class ProtectedSourceExpectationTests(unittest.TestCase):
    """Mutation checks in small temporary copies; no Java execution or real receipt copies."""
    @classmethod
    def setUpClass(cls):
        cls.historical=HERE/'preserved-input-hashes.json'
        paths=[cls.historical,*[p for p in (ROOT/'runtime/workflow').rglob('*') if p.is_file()]]
        cls.preserved={p:sha(p) for p in paths}

    @classmethod
    def tearDownClass(cls):
        if cls.preserved!={p:sha(p) for p in cls.preserved}:
            raise AssertionError('Historical baseline or workflow receipts changed')

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='simz1-protected-hashes-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        # QueueWithBuffer now delegates its unchanged budget formula to the
        # shared temporal calculation and belongs to the reviewed set.
        self.unchanged='src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QLinkLanesImpl.java'
        self.assertNotIn(self.unchanged,REVIEWED_SOURCE_EXPECTATIONS)
        full=json.loads(self.historical.read_bytes())['sha256']
        names=[*REVIEWED_SOURCE_EXPECTATIONS,self.unchanged]
        self.baseline={name:full[name] for name in names}
        for name in names:
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes((ROOT/name).read_bytes())
        # Synthetic text only: never copy a Validate/Run1000 receipt.
        dest=self.root/VALIDATE_RECEIPT;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(b'not an approval; synthetic receipt fixture\n')
        self.receipt_start_sha=sha(dest)

    def check(self):
        return check_protected_sources(self.root,self.baseline,self.receipt_start_sha)

    def test_reviewed_versions_pass_without_rewriting_baseline_or_files(self):
        baseline=copy.deepcopy(self.baseline)
        before={p:sha(p) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.check(),len(REVIEWED_SOURCE_EXPECTATIONS)+2)
        self.assertEqual(self.baseline,baseline)
        self.assertEqual(before,{p:sha(p) for p in before})

    def test_each_renewed_source_single_byte_change_fails(self):
        for name in REVIEWED_SOURCE_EXPECTATIONS:
            with self.subTest(source=name):
                path=self.root/name;original=path.read_bytes()
                path.write_bytes(bytes([original[0]^1])+original[1:])
                with self.assertRaisesRegex(AssertionError,name+': SHA256'):self.check()
                path.write_bytes(original)

    def test_missing_expected_files_fail(self):
        for name in [*REVIEWED_SOURCE_EXPECTATIONS,self.unchanged]:
            with self.subTest(source=name):
                path=self.root/name;original=path.read_bytes();path.unlink()
                with self.assertRaisesRegex(AssertionError,name+': expected file absent'):self.check()
                path.write_bytes(original)

    def test_original_baseline_source_single_byte_change_fails(self):
        path=self.root/self.unchanged;original=path.read_bytes()
        path.write_bytes(bytes([original[0]^1])+original[1:])
        with self.assertRaisesRegex(AssertionError,self.unchanged+': SHA256'):self.check()

    def test_replacements_require_the_original_historical_hash(self):
        for name in REVIEWED_SOURCE_EXPECTATIONS:
            original=self.baseline[name]
            for value in (None,REVIEWED_SOURCE_EXPECTATIONS[name]['expected_sha256']):
                with self.subTest(source=name,baseline_value=value):
                    if value is None:self.baseline.pop(name)
                    else:self.baseline[name]=value
                    with self.assertRaisesRegex(AssertionError,name+': replaced historical hash'):self.check()
                    self.baseline[name]=original

    def test_receipt_must_match_suite_start_not_historical_capture(self):
        self.baseline[VALIDATE_RECEIPT]='0'*64
        self.check()  # A newer legitimate receipt is compared with suite start.
        self.receipt_start_sha='0'*64
        with self.assertRaisesRegex(AssertionError,VALIDATE_RECEIPT+': SHA256'):self.check()

    def test_first_validate_preserves_absence_without_creating_approval(self):
        receipt=self.root/VALIDATE_RECEIPT
        receipt.unlink()  # Only the synthetic temporary fixture created in setUp.
        self.receipt_start_sha=receipt_snapshot(self.root)
        self.assertIsNone(self.receipt_start_sha)
        self.check()
        self.assertFalse(receipt.exists())
        receipt.write_bytes(b'not an approval; unexpected synthetic appearance')
        with self.assertRaisesRegex(AssertionError,'receipt appeared'):self.check()

    def test_present_receipt_cannot_disappear_or_mutate(self):
        receipt=self.root/VALIDATE_RECEIPT
        self.receipt_start_sha=receipt_snapshot(self.root)
        original=receipt.read_bytes()
        receipt.unlink()  # Only the synthetic temporary fixture created in setUp.
        with self.assertRaisesRegex(AssertionError,VALIDATE_RECEIPT+': expected file absent'):self.check()
        receipt.write_bytes(original+b'changed')
        with self.assertRaisesRegex(AssertionError,VALIDATE_RECEIPT+': SHA256'):self.check()

    def test_existing_fingerprint_covers_both_sources_and_static_expectations(self):
        from simz1_workflow_state import fingerprint
        from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
        fixed=list(REQUIRED_FIXTURE_FILES)
        variants=['scenarios/zona1/od/balanced-gateway-v1/access-review-v2/'+n for n in
                  ('config-l18-local-v1.xml','signalControl-l18-local-v1.xml','l18-local-v1.json')]
        fixed += variants
        for name in fixed:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
        name='python/test_simz1_sequence_contract.py'
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
        for name in [*REVIEWED_SOURCE_EXPECTATIONS,name,*variants]:
            with self.subTest(source=name):
                path=self.root/name;original=path.read_bytes();before=fingerprint(self.root)
                if name.endswith('.py'):
                    expected=next(iter(REVIEWED_SOURCE_EXPECTATIONS.values()))['expected_sha256'].encode()
                    path.write_bytes(original.replace(expected,b'0'*64,1))
                else:path.write_bytes(bytes([original[0]^1])+original[1:])
                self.assertNotEqual(before,fingerprint(self.root),name)
                path.write_bytes(original)


if __name__=='__main__':
    RESULTS.mkdir(parents=True,exist_ok=True)
    stream=io.StringIO()
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in
        (SequenceRegressionTests,ProtectedSourceExpectationTests))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    output=stream.getvalue();print(output);(RESULTS/'focused-tests.log').write_text(output,encoding='utf-8')
    report=getattr(SequenceRegressionTests,'report',{})
    report.update(status='PASS' if result.wasSuccessful() else 'FAIL',tests=dict(run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)),
        scope='routing regressions only; not integrated Validate, DryRun, capacity acceptance or 180K execution')
    (RESULTS/'focused-results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
