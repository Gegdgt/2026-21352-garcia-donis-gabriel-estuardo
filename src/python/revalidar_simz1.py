"""Revalidate existing SimZ1 outputs after specifically supported validator bugs.

Never launches MATSim, regenerates demand, edits native outputs, or publishes a
latest-successful/trial pointer. Default is read-only; --apply backs up the exact
old manifest and publishes completed/valid only after the FULL existing validator
passes. Graphs and the load-test acceptance gate remain separate operations.
"""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback

from simz1_run import MANIFEST, atomic_json, checked_path, load_manifest, sha256, validate_outputs

PROJECT = Path(__file__).resolve().parents[1]
ERROR_TEXT = 'element indices must be integers'
OCCUPANCY_WAIT_ERROR = 'CORRIDOR_OCCUPANCY: reservation outside domain without explicit connected passage'
OCCUPANCY_INTERVAL_ERROR = 'CORRIDOR_OCCUPANCY: passage admitted without enough published free entry interval'
COORDINATION_IMPORT_ERROR = "cannot import name 'validate_report' from 'simz1_signal_coordination'"
STEP_FORMAT_ERROR = "could not convert string to float: '00:00:01'"
STEP_FORMAT_OPERATION = 'repair_supported_fixed_day_step_format'
STEP_FORMAT_SCHEMA = 'fixed-day-step-time-format-v1'
STEP_FORMAT_EXECUTION_FINGERPRINT = '290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1'
POSTPROCESS_BASE_FINGERPRINT = 'c13e4f73ec792c64b3c899d769ff964e381b0d45dbe5cead4c770562e722309d'
POSTPROCESS_POLICY = 'src/main/resources/simz1/run1000-postprocessing-compatibility-v1.json'
# Only exact reviewed audit/presentation and additive launch-contract changes
# can bridge the historical receipt. The generator's reviewed change only pins
# exact specification bytes and verifies selection identity; demand algorithms,
# native Java, OD, physical inputs and service policies remain unchanged.
# Additive v4/v5 contracts retain the historical v3 trial and its physical base.
# All files still participate in the LIVE fingerprint.
POSTPROCESS_FILES = frozenset({
    'python/revalidar_simz1.py', 'python/simz1_workflow_state.py',
    'python/simz1_run.py', 'python/simz1_blocking_occupancy.py',
    'python/simz1_balanced_od_audit.py',
    'python/simz1_queue_context.py', 'python/simz1_continuous_replay.py',
    'python/simz1_replay_spatial_cache.py',
    'python/simz1_visual_queues.js',
    'python/simz1_continuous_loader.js', 'python/visualizador_z1_controls.js',
    'python/test_simz1_window_identity.cjs',
    'python/simz1_window_cache.py', 'python/test_simz1_window_cache.py',
    'python/simz1_queue_checkpoint.py', 'python/simz1_queue_checkpoint.cjs',
    'python/simz1_queue_checkpoints.py', 'python/test_simz1_queue_checkpoints.cjs',
    'python/test_simz1_checkpoint_contract.py',
    'python/test_simz1_checkpoint_loader.cjs',
    'python/simz1_queue_checkpoint_library.py', 'python/test_simz1_checkpoint_library.py',
    'python/simz1_queue_result_trust.py', 'python/test_simz1_queue_result_trust.py',
    'scripts/replay/start_replay.py',
    'python/test_simz1_checkpoint_pipeline.py',
    'python/simz1_queue_component_schedule.py', 'python/test_simz1_queue_component_schedule.py',
    'python/simz1_replay_workers.py', 'python/serve_simz1_continuous.py',
    'python/test_simz1_revalidate.py', 'python/test_simz1_blocking_occupancy.py',
    'python/test_simz1_blocking_occupancy_single_queue.py',
    'python/test_simz1_queue_context.py', 'python/test_simz1_continuous_replay.py',
    'python/test_simz1_replay_spatial_cache.py',
    'python/test_simz1_queue_anchor_propagation.cjs',
    'python/test_simz1_replay_workers.py', 'scripts/simz1_workflow.ps1',
    'python/simz1_queue_support.py', 'python/test_simz1_queue_support.py',
    'python/test_simz1_causal_support_graph.py',
    'python/test_simz1_queue_support_integration.py',
    'python/test_simz1_causal_queue_context.cjs',
    'python/simz1_scale_contract.py', 'python/test_simz1_random_experiment.py',
    'python/test_simz1_random_launch.py', 'python/test_simz1_freight_version.py',
    'scripts/run_massive_z1_pasante_10it.ps1',
    'scripts/run_simz1_180k_balanced_gateway.ps1',
    'scripts/simz1_launch_contract.ps1', 'scripts/watch_simz1_110k.ps1',
    'scenarios/zona1/experiments/final-20261105-random-24h-v4.json',
    'scenarios/zona1/experiments/final-20261105-run10k-24h-v5.json',
    'python/test_simz1_run10k_experiment.py', 'python/test_simz1_run10k_diagnostic.py',
    'python/test_simz1_run10k_launch.py',
    'python/generate_montecarlo_z1.py', 'python/test_simz1_preparation_identity.py',
    'python/test_simz1_dryrun_identity.py',
    'python/simz1_continuous_hud.js', 'python/visualizador_z1_continuous.html',
    'scripts/replay/start_replay.ps1', 'python/test_simz1_partial_replay.py',
    'python/test_simz1_partial_visual.cjs',
    'python/test_simz1_load_scale.py',
})
# Reviewed source transitions only; the signed run input is never rewritten.
STEP_FORMAT_TRANSITIONS = {
    'simz1_balanced_od_audit.py': {'before': '143e68f6e2e097c094e80d790f4903bb45c348f2020613f832d952f12312c6c8', 'after': '55882fb7d132530ca29752d6bfe764355bae2f998038909085da56591586c396'},
    'simz1_run.py': {'before': '767ffd045b7768656c27a631013cc2510501a13c619175ddfb35924a6df5b978', 'after': '7451f1663670102327f35662203727f294de58f2204a271c34aac22f5d70660b'},
    'simz1_temporal_passage.py': {'before': 'c19cc21777c13af3f7fadcd4c4563a6eafd0ee82b43e3384e118940b08058b05', 'after': '77ab1fafbd87a28a29f590598a0f3b56ddd2d398482a28a98a724009a2069a12'},
}
REPAIR_VERSION = 'transit-xml-occupancy-coordination-fixed-day-validator-v6'
VALIDATOR_SOURCES = ('revalidar_simz1.py', 'simz1_run.py', 'simz1_transit_events.py',
                     'simz1_priority_audit.py', 'simz1_priority_context.py',
                     'simz1_priority_classification.py', 'simz1_priority_passage.py',
                     'simz1_occupancy_audit.py', 'simz1_freight.py', 'simz1_signal_coordination.py',
                     'simz1_balanced_od_audit.py', 'simz1_temporal_passage.py',
                     'simz1_day_observation.py', 'simz1_workflow_state.py')
NATIVE_IDENTITY_FIELDS = ('run_id', 'launch_id', 'folder', 'started_utc', 'finished_utc',
                          'demand_seed', 'matsim_seed', 'returncode', 'returncode_origin',
                          'command', 'process', 'java_execution', 'inputs', 'experiment',
                          'time_horizon', 'iterations', 'last_completed_step', 'balanced_od',
                          'counts', 'demand_composition', 'agent_configuration', 'freight_transport')
FAILURE_FIELDS = ('error', 'exception_type', 'exception_traceback', 'failure_phase',
                  'failure_category', 'first_causal_error', 'causal_exception_chain', 'root_cause')


def _eligible(manifest):
    if manifest.get('status') == 'completed' and manifest.get('validation', {}).get('status') == 'valid':
        return 'already_valid'
    transit_error = (manifest.get('exception_type') == 'TypeError' and manifest.get('error') == ERROR_TEXT and
                     'simz1_transit_events.py' in manifest.get('exception_traceback', ''))
    occupancy_error = (manifest.get('exception_type') == 'ValueError' and manifest.get('error') == OCCUPANCY_WAIT_ERROR and
                       'simz1_occupancy_audit.py' in manifest.get('exception_traceback', ''))
    interval_error = (manifest.get('exception_type') == 'ValueError' and
        manifest.get('error') == OCCUPANCY_INTERVAL_ERROR and
        'simz1_occupancy_audit.py' in manifest.get('exception_traceback', '') and
        ', in _passage\n' in manifest.get('exception_traceback', ''))
    # Only the missing symbol from this exact local module and validator import
    # site is supported. Other ImportErrors, module load failures and execution
    # failures are not silently generalized into a recoverable category.
    coordination_error_text = COORDINATION_IMPORT_ERROR+' ('+str(Path(__file__).with_name('simz1_signal_coordination.py').resolve())+')'
    trace = manifest.get('exception_traceback', '')
    coordination_import_error = (manifest.get('exception_type') == 'ImportError' and
        manifest.get('error') == coordination_error_text and
        'File "'+str(Path(__file__).with_name('simz1_run.py').resolve())+'", line ' in trace and
        ', in validate_outputs\n    from simz1_signal_coordination import validate_report\nImportError: '+coordination_error_text in trace)
    validator = str(Path(__file__).with_name('simz1_run.py').resolve())
    auditor = str(Path(__file__).with_name('simz1_balanced_od_audit.py').resolve())
    step_trace = (r'  File "'+re.escape(validator)+r'", line \d+, in validate_outputs\n'
                  r'    balanced_od = validate_balanced_od\(directory, manifest\)\n'
                  r'  File "'+re.escape(auditor)+r'", line \d+, in validate_manifest\n'
                  +re.escape("    float(config.get('qsim.timeStepSize','1'))!=1):raise ValueError('Native fixed-day boundary contract mismatch')\n")
                  +re.escape('ValueError: '+STEP_FORMAT_ERROR)+r'\n?\Z')
    step_format_error = (manifest.get('exception_type') == 'ValueError' and
        manifest.get('error') == STEP_FORMAT_ERROR and
        manifest.get('validation', {}).get('error') == STEP_FORMAT_ERROR and re.search(step_trace, trace))
    if (manifest.get('status') != 'failed' or manifest.get('phase') != 'validating' or
            manifest.get('failure_phase') != 'validating' or
            manifest.get('failure_category') != 'output_validation_error' or
            manifest.get('validation', {}).get('status') != 'invalid' or
            not (transit_error or occupancy_error or interval_error or coordination_import_error or step_format_error)):
        raise ValueError('Not a supported post-run validator error; no status is changed')
    if type(manifest.get('returncode')) is not int or manifest['returncode'] != 0 or \
            manifest.get('returncode_origin') != 'natural_exit':
        raise ValueError('No recorded natural process exit=0; do not certify an interrupted simulation')
    if step_format_error:
        experiment = manifest.get('experiment') or {}
        iterations = manifest.get('iterations', {})
        first, last = iterations.get('first'), iterations.get('last')
        if (experiment.get('observation_policy') != 'fixed-day-24h-v1' or
                experiment.get('native_qsim_end_seconds') != 86399 or
                experiment.get('observation_end_seconds') != 86400 or
                manifest.get('time_horizon') != dict(start_seconds=0, end_seconds=86400) or
                type(first) is not int or type(last) is not int or first < 0 or last < first or
                type(iterations.get('requested')) is not int or iterations['requested'] != last-first+1 or
                iterations.get('completed') != list(range(first, last+1)) or
                manifest.get('last_completed_step', {}).get('seconds') != 86400 or
                manifest.get('last_completed_step', {}).get('source') != 'native_after_step_log'):
            raise ValueError('Fixed-day recovery requires the recorded complete native day and iterations')
        return 'repairable_fixed_day_step_format'
    return ('repairable_coordination_validator_import' if coordination_import_error else
            'repairable_occupancy_interval' if interval_error else
            'repairable_occupancy_request' if occupancy_error else 'repairable_transit')


def _step_format_context(directory, manifest, *, historical_signature=None):
    """Verify the exact reviewed parser repair before any output event scan."""
    from simz1_balanced_od_audit import implementation_signature, validate_implementation_signature
    from simz1_run import parameters, seconds
    saved = json.loads(checked_path(directory, manifest['balanced_od']['implementation']).read_bytes())
    compatibility = dict(schema=STEP_FORMAT_SCHEMA, transitions=copy.deepcopy(STEP_FORMAT_TRANSITIONS))
    current = implementation_signature() if historical_signature is None else historical_signature
    validate_implementation_signature(saved, current, compatibility)
    requested = parameters(checked_path(directory, manifest['inputs']['config']))
    effective = parameters(checked_path(directory, manifest['effective_config']))
    if (effective.get('qsim.timeStepSize') != '00:00:01' or
            seconds(requested.get('qsim.timeStepSize', '')) != 1 or
            any(seconds(config.get('qsim.endTime', '')) != 86399 for config in (requested, effective))):
        raise ValueError('Fixed-day repair does not permit changed native step or horizon')
    launch_id = manifest.get('launch_id', '')
    if not isinstance(launch_id, str) or not re.fullmatch('[0-9a-f]{32}', launch_id):
        raise ValueError('Fixed-day repair requires an identified launch')
    project = PROJECT
    launch_path = project/'runtime/launches'/launch_id/'state.json'
    if launch_path.is_symlink() or not launch_path.resolve().is_relative_to(project):
        raise ValueError('Launch state is outside the project')
    launch = json.loads(launch_path.read_text(encoding='utf-8-sig'))
    if (launch.get('launch_id') != launch_id or launch.get('run_id') != manifest['run_id'] or
            Path(launch.get('run_directory', '')).resolve() != directory or
            launch.get('source_fingerprint') != STEP_FORMAT_EXECUTION_FINGERPRINT or
            launch.get('dry_run') is not False or launch.get('status') != 'failed'):
        raise ValueError('Launch identity/revision does not match the supported native execution')
    provenance = dict(source_fingerprint=launch['source_fingerprint'], launch_id=launch_id,
                      launch_state=str(launch_path), launch_state_sha256=sha256(launch_path))
    return dict(implementation_compatibility=compatibility, native_execution=provenance,
                original_implementation_signature=saved, validator_implementation_signature=current)


def reviewed_postprocessing_revision(directory, manifest):
    """Read-only proof of one exact native run and reviewed successor revision.

    Reconstruct the COMPLETE prior fingerprints in memory. This is not a
    reduced live fingerprint, a new native validation, or a receipt publisher.
    The normal current Validate gate remains mandatory in the trial workflow.
    """
    from simz1_workflow_state import fingerprint_files
    root = PROJECT.resolve()
    policy_path = root/POSTPROCESS_POLICY
    if not policy_path.is_file() or policy_path.is_symlink():
        raise ValueError('Reviewed postprocessing policy absent or indirect')
    policy = json.loads(policy_path.read_bytes())
    directory = Path(directory).resolve(strict=True)
    policy_fields = {'schema', 'base_source_fingerprint', 'native_source_fingerprint',
                     'run_id', 'manifest_sha256', 'base_file_count', 'changes',
                     'additions', 'previous_native_changes'}
    if (not isinstance(policy, dict) or set(policy) != policy_fields or
            policy.get('schema') != 'simz1-run1000-postprocessing-compatibility-v1' or
            policy.get('base_source_fingerprint') != POSTPROCESS_BASE_FINGERPRINT or
            policy.get('native_source_fingerprint') != STEP_FORMAT_EXECUTION_FINGERPRINT or
            policy.get('run_id') != manifest.get('run_id') or
            policy.get('manifest_sha256') != sha256(directory/MANIFEST) or
            json.loads((directory/MANIFEST).read_bytes()) != manifest):
        raise ValueError('Reviewed postprocessing identity/policy mismatch')
    changes, additions = policy.get('changes'), policy.get('additions')
    if (not isinstance(changes, dict) or not isinstance(additions, dict) or
            not changes or set(changes) & set(additions) or
            not (set(changes) | set(additions)).issubset(POSTPROCESS_FILES)):
        raise ValueError('Unreviewed postprocessing source scope')
    valid_hash = lambda value: isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
    for name, pair in changes.items():
        if (not isinstance(pair, dict) or set(pair) != {'before', 'after'} or
                not all(valid_hash(value) for value in pair.values()) or pair['before'] == pair['after']):
            raise ValueError('Invalid reviewed source pair: '+name)
    if not all(valid_hash(value) for value in additions.values()):
        raise ValueError('Invalid reviewed source addition')
    actual, restored = {}, {}
    for path in fingerprint_files(root):
        name = path.relative_to(root).as_posix()
        if not path.is_file() or path.is_symlink():
            raise ValueError('Required compatibility source absent or indirect: '+name)
        value = sha256(path); actual[name] = value
        if name == POSTPROCESS_POLICY:
            # The policy did not exist in the old revision. Its complete bytes
            # remain included in current Validate and trial fingerprints.
            continue
        if name in additions:
            if value != additions[name]:raise ValueError('Reviewed addition changed: '+name)
            continue
        if name in changes:
            if value != changes[name]['after']:raise ValueError('Reviewed source changed: '+name)
            value = changes[name]['before']
        restored[name] = value
    if not (set(changes) | set(additions) | {POSTPROCESS_POLICY}).issubset(actual):
        raise ValueError('Reviewed source omitted from complete live inventory')
    def digest(records):
        value = hashlib.sha256()
        # Same absolute-Path ordering used by the normal fingerprint.
        for path in sorted(root/name for name in records):
            name = path.relative_to(root).as_posix()
            value.update(name.encode()+b'\0'+records[name].encode()+b'\n')
        return value.hexdigest()
    if (len(restored) != policy.get('base_file_count') or
            digest(restored) != POSTPROCESS_BASE_FINGERPRINT):
        raise ValueError('Complete reviewed baseline fingerprint differs; physical/unlisted source changed')
    native = dict(restored)
    prior = policy.get('previous_native_changes')
    if not isinstance(prior, dict) or not prior:
        raise ValueError('Missing prior native compatibility chain')
    for name, pair in prior.items():
        if (not isinstance(pair, dict) or set(pair) != {'before', 'after'} or
                not all(valid_hash(value) for value in pair.values()) or native.get(name) != pair['after']):
            raise ValueError('Prior native source chain differs: '+name)
        native[name] = pair['before']
    if digest(native) != STEP_FORMAT_EXECUTION_FINGERPRINT:
        raise ValueError('Complete original native fingerprint differs')
    return dict(schema=policy['schema'], policy_sha256=sha256(policy_path),
                current_source_fingerprint=digest(actual),
                reconstructed_base_fingerprint=digest(restored),
                reconstructed_native_fingerprint=digest(native),
                historical_sources=restored)


def recovery_compatibility(directory, manifest, *, allow_reviewed_postprocessing=False):
    """Verify a published recovery receipt; this grants no traffic/trial approval."""
    directory = Path(directory).resolve(strict=True)
    receipt = manifest.get('revalidation') or {}
    if receipt.get('operation') != STEP_FORMAT_OPERATION:
        return None
    if (manifest.get('status') != 'completed' or manifest.get('validation', {}).get('status') != 'valid' or
            receipt.get('version') != REPAIR_VERSION or receipt.get('execution_repeated') is not False or
            receipt.get('native_artifacts_modified') is not False):
        raise ValueError('Fixed-day recovery receipt is not completed/valid or has incompatible scope')
    backup = checked_path(directory, dict(path=receipt['original_manifest'], sha256=receipt['original_manifest_sha256']))
    if backup.parent != directory/'validation-history' or backup.is_symlink():
        raise ValueError('Recovery backup is outside validation history')
    original = json.loads(backup.read_bytes())
    if _eligible(original) != 'repairable_fixed_day_step_format':
        raise ValueError('Recovery backup is not the supported original failure')
    if any(manifest.get(key) != original.get(key) for key in NATIVE_IDENTITY_FIELDS):
        raise ValueError('Native execution identity changed after recovery')
    hashes = receipt.get('native_artifacts_sha256')
    if (not isinstance(hashes, dict) or not hashes or
            any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in hashes.values()) or
            any(hashes.get(record['path']) != record['sha256'] for record in original['inputs'].values()) or
            hashes.get(original['effective_config']['path']) != original['effective_config']['sha256']):
        raise ValueError('Recovery native artifact hash records are missing or changed')
    sources = {name: sha256(Path(__file__).with_name(name)) for name in VALIDATOR_SOURCES}
    revision = None
    historical_signature = None
    if receipt.get('validator_sources') != sources and allow_reviewed_postprocessing:
        revision = reviewed_postprocessing_revision(directory, manifest)
        from simz1_balanced_od_audit import implementation_signature
        historical_signature = implementation_signature()
        historical_signature['source_sha256'] = {
            name: revision['historical_sources']['python/'+name]
            for name in historical_signature['source_sha256']}
        sources = {name: revision['historical_sources']['python/'+name] for name in VALIDATOR_SOURCES}
    context = _step_format_context(directory, original, historical_signature=historical_signature)
    if any(receipt.get(key) != value for key, value in context.items()):
        raise ValueError('Recovery compatibility/provenance receipt changed')
    if receipt.get('validator_sources') != sources:
        raise ValueError('Recovery validator sources changed or are missing')
    compatibility = copy.deepcopy(context['implementation_compatibility'])
    if revision is not None:
        from simz1_balanced_od_audit import implementation_signature, validate_implementation_signature
        compatibility['schema'] = 'fixed-day-postprocessing-audit-v1'
        current = implementation_signature()
        for name, pair in compatibility['transitions'].items():
            pair['after'] = current['source_sha256'][name]
        generator = 'generate_montecarlo_z1.py'
        generator_before = revision['historical_sources']['python/'+generator]
        generator_after = current['source_sha256'].get(generator)
        if generator_after != generator_before:
            # reviewed_postprocessing_revision already required the exact
            # before/after policy and reconstructed both complete fingerprints.
            compatibility['schema'] = 'fixed-day-preparation-identity-audit-v1'
            compatibility['transitions'][generator] = dict(before=generator_before, after=generator_after)
        validate_implementation_signature(context['original_implementation_signature'], current, compatibility)
    return compatibility


def _native_snapshot(directory, manifest):
    """Hash existing run inputs and every native output, without copying them."""
    output = directory/'output'
    if not output.is_dir() or output.is_symlink():
        raise ValueError('Native output directory is absent or a symlink')
    paths = {directory/'config-simz1.xml'}
    for record in manifest['inputs'].values():
        paths.add(checked_path(directory, record))
    for path in output.rglob('*'):
        if path.is_symlink():
            raise ValueError('Native output contains a symlink: '+str(path))
        if path.is_file():
            paths.add(path)
    log = directory/'matsim-run.log'
    if log.is_file():
        paths.add(log)
    result = {}
    for path in sorted(paths):
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(directory) or not path.is_file():
            raise ValueError('Artifact absent or outside the run: '+str(path))
        result[path.relative_to(directory).as_posix()] = sha256(path)
    return result


@contextmanager
def _lock(directory, apply):
    if not apply:
        yield
        return
    path = directory/'.simz1-revalidation.lock'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError('Another revalidation or preserved lock exists: '+str(path)) from exc
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'operation': REPAIR_VERSION}))
        yield
    finally:
        path.unlink(missing_ok=True)


def revalidate(run_dir, *, apply=False, refresh_valid=False, orphan_launch_id=None, reviewed_transition=None):
    directory = Path(run_dir).resolve(strict=True)
    manifest_path = directory/MANIFEST
    if manifest_path.is_symlink():
        raise ValueError('Manifest may not be a symlink')
    with _lock(directory, apply):
        original = manifest_path.read_bytes()
        state = load_manifest(directory)
        orphan_context = None
        if orphan_launch_id is not None:
            if refresh_valid or reviewed_transition is None:
                raise ValueError('Orphan validation requires its reviewed transition and cannot refresh valid metadata')
            from simz1_launch_recovery import orphan_validation_context
            orphan_context = orphan_validation_context(directory, state, orphan_launch_id, reviewed_transition)
            eligibility = 'orphaned_pending_validation'
        else:
            eligibility = _eligible(state)
        if refresh_valid and eligibility != 'already_valid':
            raise ValueError('--refresh-valid only accepts completed/valid runs; it cannot repair failures')
        if manifest_path.read_bytes() != original:
            raise ValueError('Manifest changed while loading; no publication')
        context = None
        compatibility = None
        if eligibility == 'repairable_fixed_day_step_format':
            context = _step_format_context(directory, state)
            compatibility = context['implementation_compatibility']
        elif eligibility == 'already_valid' and (state.get('revalidation') or {}).get('operation') == STEP_FORMAT_OPERATION:
            compatibility = recovery_compatibility(directory, state)
            context = {key: copy.deepcopy(state['revalidation'][key]) for key in
                       ('implementation_compatibility', 'native_execution', 'original_implementation_signature',
                        'validator_implementation_signature')}
        before = _native_snapshot(directory, state)
        if orphan_context is not None:
            # The final event file is the retained iteration stream. Plans have
            # different serialization stages (iteration before scoring, final
            # after scoring); byte equality is not a native plan contract.
            last = state['iterations']['last']
            if before.get(f'output/ITERS/it.{last}/{last}.events.xml.gz') != before.get('output/output_events.xml.gz'):
                raise ValueError('Last iteration/output artifact mismatch: events')
            from simz1_run import population
            trips = 1 if state.get('temporal_demand') else None
            iteration_population = population(directory/f'output/ITERS/it.{last}/{last}.plans.xml.gz', trips)
            final_population = population(directory/'output/output_plans.xml.gz', trips)
            if iteration_population != final_population:
                raise ValueError('Last iteration/output population identity mismatch')
            if apply:
                history = directory/'validation-history'
                if history.is_symlink():raise ValueError('Validation history may not be a symlink')
                history.mkdir(exist_ok=True)
                original_hash = hashlib.sha256(original).hexdigest()
                pending = history/f'orphan-pending-{original_hash[:16]}.json'
                if pending.exists():
                    if pending.is_symlink() or pending.read_bytes() != original:
                        raise ValueError('Conflicting pending manifest backup')
                else:
                    with pending.open('xb') as stream:stream.write(original)
                atomic_json(history/f'orphan-inventory-{original_hash[:16]}.json',
                            dict(native_artifacts_sha256=before, context=orphan_context))
        candidate = copy.deepcopy(state)
        if eligibility == 'repairable_fixed_day_step_format':
            # In-memory validation candidate only: the failed original remains
            # unchanged on disk until every validator and integrity check passes.
            candidate['status'] = 'running'
            candidate['validation'] = dict(status='pending')
        # The previous failed attempt may already have appended effective-config
        # observations to its manifest. Do not duplicate the same observation.
        if compatibility is None:
            validate_outputs(directory, candidate)
        else:
            validate_outputs(directory, candidate, implementation_compatibility=compatibility)
        if candidate.get('validation', {}).get('status') != 'valid':
            raise ValueError('The complete validator did not report valid')
        if _native_snapshot(directory, state) != before or manifest_path.read_bytes() != original:
            raise ValueError('Run artifacts changed during validation; no publication')
        if orphan_context is not None:
            # Fresh process/source/identity checks immediately before publication.
            final_context = orphan_validation_context(directory, state, orphan_launch_id, reviewed_transition)
            for key in ('source_transition', 'native_execution', 'validated_source_receipt'):
                if final_context[key] != orphan_context[key]:
                    raise ValueError('Orphan recovery provenance changed during validation')
            context = dict(orphan_recovery=orphan_context,
                           orphan_final_observation=final_context['observation'])
        unique = []
        for observation in candidate.get('configuration_overrides', []):
            if observation not in unique:
                unique.append(observation)
        candidate['configuration_overrides'] = unique
        outcome = dict(schema_version=1, repair_version=REPAIR_VERSION, run_id=state['run_id'],
                       run_directory=str(directory), matsim_executed=False,
                       native_artifacts_modified=False, native_artifacts_checked=len(before),
                       latest_successful_modified=False, trial_authorized=False,
                       results={key: {'counts': value['counts'],
                                      'public_transport_events': value.get('public_transport_events', {}),
                                      'freight_transport_events': value.get('freight_transport_events', {}),
                                      'priority_events': value.get('priority_events', {})}
                                for key, value in candidate['results'].items()})
        if context is not None:
            outcome.update(copy.deepcopy(context))
        if eligibility == 'already_valid' and not refresh_valid:
            outcome['status'] = 'already_valid_rechecked_no_metadata_change'
            return outcome
        if not apply:
            outcome['status'] = 'revalidation_pass_not_published'
            outcome['next'] = 'Repeat with --apply to back up and publish the validated manifest'
            return outcome
        original_hash = hashlib.sha256(original).hexdigest()
        history = directory/'validation-history'
        if history.is_symlink():
            raise ValueError('Validation history may not be a symlink')
        history.mkdir(exist_ok=True)
        backup = history/f'run-manifest.before-{original_hash[:16]}.json'
        if backup.exists():
            if backup.is_symlink() or backup.read_bytes() != original:
                raise ValueError('Conflicting manifest backup; no publication')
        else:
            # Exclusive creation preserves any existing backup and exact original bytes.
            with backup.open('xb') as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
        recovered = {key: state[key] for key in FAILURE_FIELDS if key in state}
        for key in FAILURE_FIELDS:
            candidate.pop(key, None)
        candidate['status'] = 'completed'
        candidate['phase'] = 'completed'
        candidate['revalidation'] = dict(
            version=REPAIR_VERSION, validated_utc=datetime.now(timezone.utc).isoformat(),
            operation='refresh_valid_metadata' if refresh_valid else
                {'repairable_occupancy_request': 'repair_supported_occupancy_request_error',
                 'repairable_occupancy_interval': 'repair_supported_occupancy_interval_cap',
                 'repairable_coordination_validator_import': 'repair_supported_coordination_validator_import',
                 'repairable_fixed_day_step_format': STEP_FORMAT_OPERATION,
                 'orphaned_pending_validation': 'resume_orphaned_native_validation_v1',
                 'repairable_transit': 'repair_supported_transit_error'}[eligibility],
            original_manifest=backup.relative_to(directory).as_posix(),
            original_manifest_sha256=original_hash, original_failure=recovered,
            execution_repeated=False, native_artifacts_modified=False,
            native_artifacts_sha256=before,
            validator_sources={name: sha256(Path(__file__).with_name(name)) for name in VALIDATOR_SOURCES},
            scope='full output integrity revalidation; not traffic quality or load-test acceptance')
        if context is not None:
            candidate['revalidation'].update(copy.deepcopy(context))
            if refresh_valid:
                # Preserve the original failure anchor when refreshing an already
                # recovered run; the new backup records this metadata refresh.
                candidate['revalidation']['operation'] = STEP_FORMAT_OPERATION
                for key in ('original_manifest', 'original_manifest_sha256', 'original_failure'):
                    candidate['revalidation'][key] = copy.deepcopy(state['revalidation'][key])
                candidate['revalidation']['previous_validation_manifest'] = backup.relative_to(directory).as_posix()
                candidate['revalidation']['previous_validation_manifest_sha256'] = original_hash
        # Keep the original simulation start/end, command, return code and seeds.
        if manifest_path.read_bytes() != original:
            raise ValueError('Manifest changed before publication; preserve the backup')
        atomic_json(manifest_path, candidate)
        outcome.update(status='completed_valid_revalidated', manifest_backup=str(backup))
        return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Back up and publish metadata only after full validation')
    parser.add_argument('--refresh-valid', action='store_true', help='Recompute metadata of a completed/valid run after validator updates; never repairs a failed run')
    parser.add_argument('--orphan-launch-id', help='Explicit launch whose recorded natural exit preceded interrupted validation')
    parser.add_argument('--reviewed-transition', type=Path)
    args = parser.parse_args(argv)
    try:
        result = revalidate(args.run_dir, apply=args.apply, refresh_valid=args.refresh_valid,
                            orphan_launch_id=args.orphan_launch_id, reviewed_transition=args.reviewed_transition)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        print('Revalidation stopped; native artifacts retained: '+str(exc), file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
