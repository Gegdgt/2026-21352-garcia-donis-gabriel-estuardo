"""Shared closure and explicit recovery; never invokes QSim or edits native outputs.

The ordinary launcher and recovery use validate_launch_closure. Recovery is a new
receipt under runtime/recoveries, anchored to the immutable failed launch. An
exact reviewed complete-inventory transition is required after source changes.
The explicit pending-validation mode publishes manifest metadata only after the
original full native validator succeeds, retaining the pending original verbatim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback
import uuid

from simz1_workflow_state import PROJECT, fingerprint, fingerprint_files, sha

# Changes to routing, demand, native Java, auditors, geometry, or graphics are
# deliberately absent. Every allowed change still participates in fingerprint().
REVIEWABLE = frozenset({
    'python/revalidar_simz1.py', 'python/test_simz1_revalidate.py',
    'python/simz1_launch_recovery.py', 'python/test_simz1_launch_recovery.py',
    'python/simz1_configuration_contract.py', 'python/test_simz1_configuration_contract.py',
    'python/simz1_workflow_state.py', 'python/ejecutar_simz1.py',
    'python/simz1_experiment_preflight.py',
    'scripts/recover_simz1_launch.ps1', 'scripts/simz1_workflow.ps1',
    'scripts/run_massive_z1_pasante_10it.ps1', 'scripts/simz1_launch_contract.ps1',
    'scripts/run_simz1_180k_balanced_gateway.ps1', 'scripts/check_simz1_110k_balanced_gateway.ps1',
    'scripts/run_simz1_with_analysis.ps1',
    'python/test_simz1_dryrun_identity.py', 'python/test_simz1_preparation_identity.py',
    'python/test_simz1_launch_failure.py', 'python/test_simz1_package_launcher.py',
    'python/test_simz1_random_launch.py', 'python/test_simz1_run10k_launch.py',
    'python/test_simz1_load_scale.py', 'python/test_simz1_massive_launch.py',
    'python/test_simz1_trial_experiment.py',
    'python/simz1_scale_contract.py',
})

ORPHAN_RECOVERY_VERSION = 'simz1-orphan-native-closure-v1'
ORPHAN_RECOVERY_FILES = frozenset({
    'python/revalidar_simz1.py', 'python/test_simz1_revalidate.py',
    'python/simz1_launch_recovery.py', 'python/test_simz1_launch_recovery.py',
    'scripts/recover_simz1_launch.ps1',
})


def read(path):
    value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('Expected JSON object: '+str(path))
    return value


def inventory_digest(records, root=PROJECT):
    digest=hashlib.sha256()
    for path in sorted(Path(root)/name for name in records):
        name=path.relative_to(root).as_posix()
        digest.update(name.encode()+b'\0'+records[name].encode()+b'\n')
    return digest.hexdigest()


def reviewed_transition(path, native_fingerprint, *, root=PROJECT):
    """Restore the complete producing revision, without omitting current files."""
    root=Path(root).resolve(); review=read(path)
    if (set(review) != {'schema','native_source_fingerprint','current_source_fingerprint','before','after'} or
            review.get('schema')!='simz1-launch-closure-reviewed-transition-v1' or
            review.get('native_source_fingerprint')!=native_fingerprint):
        raise ValueError('Recovery source transition identity differs')
    before,after=review['before'],review['after']
    if not isinstance(before,dict) or not isinstance(after,dict) or not before:
        raise ValueError('Recovery requires complete source inventories')
    for records in (before,after):
        for name,value in records.items():
            if (not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or
                    not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value)):
                raise ValueError('Invalid source inventory entry')
    actual={p.relative_to(root).as_posix():sha(p) for p in fingerprint_files(root)}
    if (after!=actual or inventory_digest(before,root)!=native_fingerprint or
            inventory_digest(after,root)!=review['current_source_fingerprint']):
        raise ValueError('Complete source fingerprint transition differs')
    changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
    if not changed.issubset(REVIEWABLE) or before.keys()-after.keys():
        raise ValueError('Unreviewed physical/source change or source deletion: '+','.join(sorted(changed-REVIEWABLE)))
    return dict(path=str(Path(path).resolve()),sha256=sha(path),
                native_source_fingerprint=native_fingerprint,
                current_source_fingerprint=review['current_source_fingerprint'],changed=sorted(changed))


def validate_launch_closure(project, request_path, run_dir):
    """Read-only closure used after the real pipeline and in recovery/fixtures.

    Synthetic test fixtures may use a network request. Official balanced launches
    require their exact pinned versioned selection; neither path publishes native
    validation or a trial receipt.
    """
    project=Path(project).resolve(); run=Path(run_dir).resolve(strict=True)
    request=read(request_path); manifest=read(run/'run-manifest.json')
    from simz1_run import checked_path
    from simz1_configuration_contract import planned_configuration, normalize_configuration, validate_run_configuration, expected_from_selection
    if (manifest.get('status')!='completed' or manifest.get('validation',{}).get('status')!='valid' or
            manifest.get('returncode')!=0 or type(manifest.get('returncode')) is not int or
            manifest.get('returncode_origin')!='natural_exit'):
        raise ValueError('Closure requires existing native completed/valid and natural exit=0')
    if (request.get('dry_run') is not False or manifest.get('launch_id')!=request.get('launch_id') or
            Path(request.get('run_directory','')).resolve()!=run or Path(manifest.get('folder','')).resolve()!=run):
        raise ValueError('Closure launch/run identity differs')
    first=request['first_iteration'];last=request['last_iteration']; iterations=list(range(first,last+1))
    if (type(first) is not int or type(last) is not int or first<0 or last<first or
            request.get('iterations')!=len(iterations) or
            manifest.get('iterations')!={'first':first,'last':last,'requested':len(iterations),'completed':iterations} or
            manifest.get('demand_seed')!=request.get('demand_seed') or
            manifest.get('matsim_seed')!=request.get('matsim_seed')):
        raise ValueError('Closure iterations or seeds differ')
    selected=request.get('experiment')
    if selected:
        from simz1_scale_contract import experiment, verify_launch_request, verify_selection_identity, require_scale
        pinned=checked_path(run,manifest['inputs']['input:experiment-specification.json'])
        expected_selection=experiment(pinned,selected['scenario'])
        verify_launch_request(request,expected_selection)
        native_selection=dict(manifest['experiment'])
        native_selection.pop('initial_population_sha256',None);native_selection.pop('population_identity_basis',None)
        verify_selection_identity(native_selection,expected_selection)
        expected_mix=require_scale(selected['total_non_public_vehicles'],selected['demand_seed'],
                                   selected['iterations'],pinned,selected['scenario'])
        mix=manifest.get('demand_composition',{});counts=manifest['counts']
        if (mix.get('family_counts')!={k:expected_mix[k] for k in ('carro','moto','pesado')} or
                mix.get('total_non_public_vehicles')!=selected['total_non_public_vehicles'] or
                counts.get('non_public_vehicles_configured')!=selected['total_non_public_vehicles'] or
                counts.get('public_transport_vehicles_configured')!=selected['public_vehicles'] or
                counts.get('all_vehicles_configured')!=selected['total_non_public_vehicles']+selected['public_vehicles']):
            raise ValueError('Closure native population/composition differs')
        if (manifest.get('time_horizon')!={'start_seconds':0,'end_seconds':selected['observation_end_seconds']} or
                manifest.get('last_completed_step',{}).get('seconds')!=selected['observation_end_seconds'] or
                manifest.get('last_completed_step',{}).get('source')!='native_after_step_log'):
            raise ValueError('Closure native day boundary differs')
        base=project/selected['base_inputs']['source_config']
        expected=planned_configuration(base,first_iteration=first,last_iteration=last,
                                       native_end_seconds=selected['native_qsim_end_seconds'])
        from simz1_scale_contract import ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA
        if expected_selection.get('schema') in (ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA):
            expected = expected_from_selection(expected_selection, project=project)
    else:
        if request.get('od_mode')=='balanced-gateway-v1':raise ValueError('Balanced closure requires versioned experiment')
        expected=normalize_configuration(run/'config-simz1.xml')
    configuration=validate_run_configuration(run,expected=expected)
    from simz1_report_package import _source_files, _validate_existing, PACKAGE_MANIFEST
    products=[]
    for iteration in iterations:
        native,analyzed,status,sources=_source_files(run,iteration)
        analysis=run/'analysis'/f'it.{iteration}'
        quality_path=analysis/'graficas_perfiles/calidad_resultados.json';quality=read(quality_path)
        if (quality.get('run_id')!=manifest['run_id'] or quality.get('iteration')!=iteration or
                quality.get('status') not in ('screening_pass','review_required','not_applicable_no_private_demand')):
            raise ValueError('Closure screening identity/status differs')
        name=run.name if iteration==0 else run.name+f'-it.{iteration}'
        package=run/'entregables'/name
        identity=dict(schema_version=1,run_name=run.name,run_id=manifest['run_id'],iteration=iteration,
                      run_manifest_sha256=sha(run/'run-manifest.json'),
                      analysis_manifest_sha256=sha(analysis/'analysis-manifest.json'),
                      analysis_fingerprint=analyzed['fingerprint'])
        if not _validate_existing(package,identity,sources):raise ValueError('Closure package missing, changed or mixed iteration')
        products.append(dict(iteration=iteration,screening=quality['status'],quality_sha256=sha(quality_path),
                             analysis_manifest_sha256=identity['analysis_manifest_sha256'],
                             package_manifest_sha256=sha(package/'docs'/PACKAGE_MANIFEST)))
    return dict(schema='simz1-launch-closure-v1',status='verified',run_id=manifest['run_id'],
                launch_id=request['launch_id'],request_sha256=sha(request_path),
                manifest_sha256=sha(run/'run-manifest.json'),configuration=configuration,products=products,
                native_status='completed',native_validation='valid',native_status_modified=False)


def recovery_identity(launch_id, *, root=PROJECT):
    if not isinstance(launch_id,str) or not re.fullmatch('[a-f0-9]{32}',launch_id):raise ValueError('Invalid failed LaunchId')
    launch=Path(root)/'runtime/launches'/launch_id
    request=read(launch/'request.json');state=read(launch/'state.json')
    run=Path(request['run_directory']).resolve(strict=True);manifest=read(run/'run-manifest.json')
    if (state.get('launch_id')!=launch_id or request.get('launch_id')!=launch_id or
            state.get('status')!='postprocessing_failed' or state.get('dry_run') is not False or
            request.get('dry_run') is not False or state.get('native_status')!='completed' or
            state.get('native_validation')!='valid' or manifest.get('launch_id')!=launch_id or
            manifest.get('run_id')!=state.get('run_id') or Path(state.get('run_directory','')).resolve()!=run or
            manifest.get('status')!='completed' or manifest.get('validation',{}).get('status')!='valid'):
        raise ValueError('Recovery requires an identified postprocessing failure with native completed/valid')
    return launch,request,state,run,manifest


def orphan_validation_context(run, manifest, launch_id, transition_path, *, root=PROJECT):
    """Prove an orphan after recorded natural exit, never infer an exit from logs.

    This only admits the pending validator. It does not approve any native output.
    Current sources must differ from the producing revision ONLY in this recovery
    entry point and its tests. The original Validate receipt is never republished.
    """
    from simz1_resource_monitor import observe_launch
    from simz1_run import checked_path, completed_iterations
    from simz1_scale_contract import experiment, verify_launch_request, verify_selection_identity
    root=Path(root).resolve();run=Path(run).resolve(strict=True)
    if not isinstance(launch_id,str) or not re.fullmatch('[a-f0-9]{32}',launch_id):
        raise ValueError('Invalid orphan LaunchId')
    launch=root/'runtime/launches'/launch_id
    request=read(launch/'request.json');state=read(launch/'state.json')
    if (manifest.get('status')!='running' or manifest.get('phase')!='validating' or
            manifest.get('validation')!={'status':'pending'} or
            any(manifest.get(k) for k in ('error','exception_type','failure_category','exception_traceback')) or
            type(manifest.get('returncode')) is not int or manifest['returncode']!=0 or
            manifest.get('returncode_origin')!='natural_exit' or
            type(manifest.get('process',{}).get('returncode')) is not int or
            manifest['process']['returncode']!=0 or manifest['process'].get('returncode_origin')!='natural_exit'):
        raise ValueError('Orphan recovery requires pending validation after recorded natural exit=0')
    expected_run=root/'scenarios/zona1/montecarlo'/('run-bg'+str(request.get('minimum_non_public_vehicles',0)//1000)+'-'+launch_id)
    if (state.get('launch_id')!=launch_id or request.get('launch_id')!=launch_id or
            manifest.get('launch_id')!=launch_id or manifest.get('run_id')!=state.get('run_id') or
            not re.fullmatch('simz1-[a-f0-9]{32}',manifest.get('run_id','')) or
            any(Path(owner.get(field,'')).resolve()!=run for owner,field in
                ((state,'run_directory'),(request,'run_directory'),(manifest,'folder'))) or
            run!=expected_run.resolve() or state.get('status')!='running' or
            state.get('phase')!='simulation_and_analysis' or
            any(owner.get('dry_run') is not False for owner in (state,request)) or
            request.get('od_mode')!='balanced-gateway-v1' or
            request.get('postprocessing_policy')!='native_diagnostic_v1'):
        raise ValueError('Orphan launch/run/policy identity differs')
    first=request.get('first_iteration');last=request.get('last_iteration')
    if (type(first) is not int or type(last) is not int or first!=0 or last!=0 or
            request.get('iterations')!=1 or
            any(manifest.get('iterations',{}).get(k)!=v for k,v in
                dict(first=first,last=last,requested=1).items()) or
            manifest.get('iterations',{}).get('completed') not in ([],[0]) or
            completed_iterations(run/'output')!=[0] or
            manifest.get('time_horizon')!={'start_seconds':0,'end_seconds':86400} or
            manifest.get('last_completed_step',{}).get('seconds')!=86400 or
            manifest.get('last_completed_step',{}).get('source')!='native_after_step_log' or
            manifest.get('demand_seed')!=request.get('demand_seed') or
            manifest.get('matsim_seed')!=request.get('matsim_seed')):
        raise ValueError('Orphan native horizon/iterations/seeds differ')
    pinned=checked_path(run,manifest['inputs']['input:experiment-specification.json'])
    selection=experiment(pinned,request['experiment']['scenario'])
    verify_launch_request(request,selection)
    recorded=dict(manifest['experiment'])
    recorded.pop('initial_population_sha256',None);recorded.pop('population_identity_basis',None)
    verify_selection_identity(recorded,selection)
    transition=reviewed_transition(transition_path,state['source_fingerprint'],root=root)
    if not set(transition['changed']).issubset(ORPHAN_RECOVERY_FILES):
        raise ValueError('Orphan recovery may change only recovery entry points and tests')
    receipt_path=root/'runtime/workflow/validated-balanced-gateway-v1.json'
    receipt=read(receipt_path)
    if (receipt.get('status')!='integrated_validate_pass' or receipt.get('od_mode')!='balanced-gateway-v1' or
            receipt.get('source_fingerprint')!=state['source_fingerprint']):
        raise ValueError('Producing revision lacks its original integrated validation receipt')
    observation=observe_launch(launch)
    if (observation.get('enumeration_complete') is not True or observation.get('tree_absent') is not True or
            observation.get('stream_final') is not True or observation.get('writer_alive') is not False or
            observation.get('live_processes')!=[] or observation.get('ambiguous_pids')!=[] or
            observation.get('observed_status')!='orphaned/incomplete' or
            observation.get('run_id')!=manifest['run_id'] or observation.get('launch_id')!=launch_id):
        raise ValueError('Orphan process absence is not proven; no publication')
    return dict(schema=ORPHAN_RECOVERY_VERSION,source_transition=transition,observation=observation,
        native_execution=dict(launch_id=launch_id,run_id=manifest['run_id'],source_fingerprint=state['source_fingerprint'],
            launch_state_sha256=sha(launch/'state.json'),request_sha256=sha(launch/'request.json'),
            original_manifest_sha256=sha(run/'run-manifest.json')),
        validated_source_receipt=dict(path=str(receipt_path),sha256=sha(receipt_path)))


def recover_pending(launch_id, transition_path, *, root=PROJECT):
    """Resume native validation, then the existing analysis/package/closure path.

    The interrupted gateway stays historical. No trial, latest-successful, or
    acceptance receipt is published. Review-required products remain available.
    """
    from revalidar_simz1 import revalidate
    from simz1_run import atomic_json
    root=Path(root).resolve();launch=root/'runtime/launches'/launch_id
    request=read(launch/'request.json');run=Path(request['run_directory']).resolve(strict=True)
    manifest=read(run/'run-manifest.json')
    context=orphan_validation_context(run,manifest,launch_id,transition_path,root=root)
    recovery_id=uuid.uuid4().hex;directory=root/'runtime/recoveries'/recovery_id;directory.mkdir(parents=True)
    for name,path in (('original-state.json',launch/'state.json'),('original-request.json',launch/'request.json'),
                      ('original-run-manifest.json',run/'run-manifest.json')):
        with (directory/name).open('xb') as stream:stream.write(path.read_bytes())
    protected={launch/'state.json':sha(launch/'state.json'),launch/'request.json':sha(launch/'request.json'),
               Path(context['validated_source_receipt']['path']):context['validated_source_receipt']['sha256']}
    trial=root/'runtime/workflow/trial-balanced-gateway-v1.json'
    if trial.is_file():protected[trial]=sha(trial)
    outcome=dict(schema=ORPHAN_RECOVERY_VERSION,recovery_id=recovery_id,original_launch_id=launch_id,
        run_id=manifest['run_id'],run_directory=str(run),status='validating',context=context,
        native_execution_repeated=False,native_artifacts_modified=False,historical_launch_modified=False,
        started_utc=datetime.now(timezone.utc).isoformat(),steps=[],trial_authorized=False)
    atomic_json(directory/'recovery-state.json',outcome)
    print('RECOVERY_DIRECTORY='+str(directory),flush=True)
    def execute(label,args,allowed=(0,)):
        print('RECOVERY_STEP='+label,flush=True)
        with (directory/(label+'.log')).open('x',encoding='utf-8') as log:
            result=subprocess.run(args,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        outcome['steps'].append(dict(step=label,command=args,exit_code=result.returncode))
        atomic_json(directory/'recovery-state.json',outcome)
        if result.returncode not in allowed:raise ValueError(f'{label} failed exit={result.returncode}; no QSim retry')
        return result.returncode
    try:
        print('RECOVERY_STEP=native-validation (original full validator; no QSim)',flush=True)
        validation=revalidate(run,apply=True,orphan_launch_id=launch_id,reviewed_transition=transition_path)
        atomic_json(directory/'native-validation.json',validation)
        protected[run/'run-manifest.json']=sha(run/'run-manifest.json')
        native_hashes=read(run/'run-manifest.json')['revalidation']['native_artifacts_sha256']
        outcome['native_validation_exit_code']=0
        outcome['status']='postprocessing';atomic_json(directory/'recovery-state.json',outcome)
        execute('analysis-package-screening',['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(root/'scripts/run_simz1_with_analysis.ps1'),'-AnalysisOnly','-RunDir',str(run),
            '-ExpectedRunId',manifest['run_id']],allowed=(0,3))
        execute('operations-0',[sys.executable,'-B',str(root/'python/simz1_operational_report.py'),
            '--run-dir',str(run),'--iteration','0'])
        closure=validate_launch_closure(root,launch/'request.json',run)
        if any(sha(p)!=h for p,h in protected.items()):raise ValueError('Historical launch/approval evidence changed')
        if fingerprint(root)!=context['source_transition']['current_source_fingerprint']:
            raise ValueError('Sources changed during recovery')
        current=read(run/'run-manifest.json')
        from revalidar_simz1 import _native_snapshot
        if _native_snapshot(run,current)!=native_hashes:
            raise ValueError('Native files changed during postprocessing')
        screening=[row['screening'] for row in closure['products']]
        exit_code=3 if 'review_required' in screening else 0
        outcome.update(status='closure_recovered',closure=closure,exit_code=exit_code,screening=screening,
            native_status='completed',native_validation='valid',postprocessing_policy=request['postprocessing_policy'],
            replay_status='manual_after_native_validation',visual_acceptance='not_certified',
            acceptance='not_promoted_by_recovery',protected_artifacts={str(p):h for p,h in protected.items()},
            finished_utc=datetime.now(timezone.utc).isoformat())
        atomic_json(directory/'recovery-receipt.json',outcome)
        atomic_json(directory/'recovery-state.json',outcome)
        return outcome
    except BaseException as exc:
        current=read(run/'run-manifest.json')
        outcome.update(status='recovery_failed',error=str(exc),exception_type=type(exc).__name__,exit_code=1,
            exception_traceback=traceback.format_exc(),
            native_status=current.get('status'),native_validation=current.get('validation',{}).get('status'),
            finished_utc=datetime.now(timezone.utc).isoformat())
        atomic_json(directory/'recovery-failure.json',outcome);atomic_json(directory/'recovery-state.json',outcome)
        raise


def require_recovery_receipt(trial, *, root=PROJECT):
    """A recovered trial retains its immutable closure and failed-launch anchor."""
    reference=trial.get('launch_recovery')
    if reference is None:return
    root=Path(root).resolve()
    if (not isinstance(reference,dict) or set(reference)!={'path','sha256','recovery_id'} or
            not isinstance(reference.get('recovery_id'),str) or
            not re.fullmatch('[a-f0-9]{32}',reference['recovery_id'])):
        raise ValueError('Invalid recovered trial receipt reference')
    expected=root/'runtime/recoveries'/reference['recovery_id']/'recovery-receipt.json'
    path=Path(reference['path'])
    if path.resolve()!=expected.resolve() or path.is_symlink() or sha(path)!=reference['sha256']:
        raise ValueError('Recovered trial receipt missing, indirect or changed')
    receipt=read(path)
    if (receipt.get('schema')!='simz1-launch-recovery-v1' or receipt.get('status')!='closure_recovered' or
            receipt.get('recovery_id')!=reference['recovery_id'] or receipt.get('run_id')!=trial.get('run_id') or
            Path(receipt.get('run_directory','')).resolve()!=Path(trial.get('run_directory','')).resolve() or
            receipt.get('source_transition',{}).get('current_source_fingerprint')!=trial.get('source_fingerprint') or
            receipt.get('closure',{}).get('manifest_sha256')!=trial.get('manifest_sha256') or
            any(receipt.get(key) is not False for key in
                ('native_execution_repeated','native_artifacts_modified','historical_launch_modified'))):
        raise ValueError('Recovered trial identity or provenance differs')
    launch,request,state,run,manifest=recovery_identity(receipt.get('original_launch_id'),root=root)
    for protected in (launch/'request.json',launch/'state.json',run/'run-manifest.json'):
        if receipt.get('protected_artifacts',{}).get(str(protected))!=sha(protected):
            raise ValueError('Recovered trial original launch/native evidence changed')
    transition=receipt['source_transition']
    if sha(transition['path'])!=transition.get('sha256'):
        raise ValueError('Reviewed source transition changed or is absent')


def recover(launch_id, transition_path, *, root=PROJECT):
    from simz1_workflow_state import require_balanced_validation, inspect, _publish_inspected_trial
    from simz1_run import checked_path
    root=Path(root).resolve();launch,request,state,run,manifest=recovery_identity(launch_id,root=root)
    require_balanced_validation()
    transition=reviewed_transition(transition_path,state['source_fingerprint'],root=root)
    # Pins before any recovery writes. Native artifact hashes are checked by the
    # inspector; this snapshot additionally detects changes while postprocessing.
    protected={launch/'request.json':sha(launch/'request.json'),launch/'state.json':sha(launch/'state.json'),
               run/'run-manifest.json':sha(run/'run-manifest.json')}
    for item in manifest['results'].values():
        for name in ('events','plans','network'):
            record=item[name];path=(run/record['path']).resolve()
            if (not path.is_relative_to(run) or not path.is_file() or
                    not isinstance(record.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',record['sha256'])):
                raise ValueError('Recovery native artifact is absent or outside the run')
            if request['experiment']['scenario']!='run1000':checked_path(run,record)
            # Trial inspect below verifies these exact records before any work;
            # do not hash a large event file twice before that shared inspector.
            protected[path]=record['sha256']
    recovery_id=uuid.uuid4().hex;directory=root/'runtime/recoveries'/recovery_id;directory.mkdir(parents=True)
    outcome=dict(schema='simz1-launch-recovery-v1',recovery_id=recovery_id,original_launch_id=launch_id,
                 run_id=manifest['run_id'],run_directory=str(run),source_transition=transition,
                 native_execution_repeated=False,native_artifacts_modified=False,
                 historical_launch_modified=False,started_utc=datetime.now(timezone.utc).isoformat(),status='running')
    def execute(label,args):
        with (directory/(label+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run(args,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise ValueError(f'Recovery {label} failed exit={result.returncode}; native evidence retained')
    try:
        closure=validate_launch_closure(root,launch/'request.json',run)
        if any(p['screening']!='screening_pass' for p in closure['products']):
            raise ValueError('Recovery screening requires review; no trial acceptance')
        inspected=(inspect(run,1000) if request['experiment']['scenario']=='run1000' else None)
        for iteration in manifest['iterations']['completed']:
            execute(f'operations-{iteration}',[sys.executable,'-B',str(root/'python/simz1_operational_report.py'),
                                              '--run-dir',str(run),'--iteration',str(iteration)])
            # The shared closure has verified the existing balanced report and
            # its packaged hashes. Do not regenerate an already valid product.
        policy=request['postprocessing_policy']
        if policy=='automatic_replay_v1':
            execute('replay',[sys.executable,'-B',str(root/'scripts/replay/prepare_replay.py'),
                '--run-dir',str(run),'--iteration',str(manifest['iterations']['last']),
                '--sqlite-budget-gib',str(request['sqlite_budget_gib']),
                '--scratch-budget-gib',str(request['scratch_budget_gib'])])
            outcome['replay_status']='prepared_identity_verified'
        elif policy=='native_diagnostic_v1':outcome['replay_status']='manual_after_native_validation'
        else:raise ValueError('Unsupported recovery postprocessing policy')
        if any(sha(p)!=h for p,h in protected.items()):raise ValueError('Native/launch evidence changed during recovery')
        if fingerprint()!=transition['current_source_fingerprint']:raise ValueError('Sources changed during recovery')
        # Recheck products after reports; their package must still match exactly.
        closure=validate_launch_closure(root,launch/'request.json',run)
        outcome.update(status='closure_recovered',closure=closure,postprocessing_policy=policy,
                       trial_acceptance='separate official trial receipt required',
                       protected_artifacts={str(p):h for p,h in protected.items()},
                       finished_utc=datetime.now(timezone.utc).isoformat())
        receipt=directory/'recovery-receipt.json'
        trial_path=root/'runtime/workflow/trial-balanced-gateway-v1.json'
        if inspected is not None and trial_path.exists():
            previous=directory/'prior-trial.json'
            with previous.open('xb') as stream:stream.write(trial_path.read_bytes())
            outcome['prior_trial']=dict(path=str(previous),sha256=sha(previous))
        receipt.write_text(json.dumps(outcome,indent=2),encoding='utf-8')
        if inspected is not None:
            trial=_publish_inspected_trial(inspected,trial_path,
                transition['current_source_fingerprint'],
                launch_recovery=dict(path=str(receipt),sha256=sha(receipt),recovery_id=recovery_id))
            (directory/'trial-acceptance.json').write_text(json.dumps(trial,indent=2),encoding='utf-8')
        return outcome
    except Exception as exc:
        outcome.update(status='postprocessing_failed',error=str(exc),finished_utc=datetime.now(timezone.utc).isoformat())
        (directory/'recovery-failure.json').write_text(json.dumps(outcome,indent=2),encoding='utf-8')
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('verify-closure','recover','recover-pending'))
    parser.add_argument('--request',type=Path);parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--launch-id');parser.add_argument('--reviewed-transition',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        result=(validate_launch_closure(PROJECT,args.request,args.run_dir) if args.action=='verify-closure'
                else recover_pending(args.launch_id,args.reviewed_transition) if args.action=='recover-pending'
                else recover(args.launch_id,args.reviewed_transition))
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
        print(json.dumps(result,indent=2));return result.get('exit_code',0)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print('Closure blocked; native files retained; inspect recovery state: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
