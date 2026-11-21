"""Bind the 1,000-person acceptance gate to one explicit validated run and code revision."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from simz1_transit_accounting import verified_weekday_fleet

PROJECT=Path(__file__).resolve().parents[1]


def require_balanced_validation():
    receipt = json.loads((PROJECT/'runtime/workflow/validated-balanced-gateway-v1.json').read_text(encoding='utf-8-sig'))
    if (receipt.get('status') != 'integrated_validate_pass' or receipt.get('od_mode') != 'balanced-gateway-v1' or
            receipt.get('source_fingerprint') != fingerprint()):
        raise ValueError('Falta Validate integrado balanced-gateway-v1 para esta revision; sin reutilizar aprobacion network')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def fingerprint_files(root=PROJECT):
    """Complete dependency inventory, shared by live and historical comparison.

    The live fingerprint never removes postprocessor files or compatibility
    policies. A historical comparison may describe reviewed files absent then.
    """
    root=Path(root);files={root/'pom.xml',root/'scenarios/zona1/config-simz1.xml',root/'scenarios/zona1/network.xml',root/'scenarios/zona1/agent-types-car-moto-v1.json'}
    for base,patterns in (('src/main/java',('*.java',)),('src/test/java',('*.java',)),('python',('*.py','*.js','*.cjs','*.html')),('scripts',('*.ps1','*.py')),('scenarios/zona1/transit/weekday-v2',('*.json',)),('scenarios/zona1/freight/weekday-v1',('*.json',)),('scenarios/zona1/freight/weekday-v2',('*.json',))):
        for pattern in patterns:files.update((root/base).rglob(pattern))
    files.update((root/'scenarios/zona1').glob('*.xml'))
    files.update((root/'scenarios/zona1').glob('*.osm'))
    files.update((root/'scenarios/zona1').glob('*.json'))
    variant = root/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2'
    files.update(variant/name for name in ('config-l18-local-v1.xml','signalControl-l18-local-v1.xml','l18-local-v1.json'))
    # All versioned freight inputs, including compact-v3, bind the approval.
    files.update((root/'scenarios/zona1/freight').rglob('*.json'))
    files.update((root/'src/main/resources/simz1').glob('*.json'))
    files.add(root/'src/main/resources/simz1/freight-completion-v1.json')
    files.add(root/'src/main/resources/simz1/freight-entry-completion-v2.json')
    files.add(root/'scenarios/zona1/experiments/final-20261108-freight-entry-24h-v7.json')
    files.add(root/'scenarios/zona1/experiments/final-20261102-v1.json')
    files.add(root/'src/main/resources/simz1/day-observation-v1.json')
    files.add(root/'scenarios/zona1/experiments/final-20261103-24h-v2.json')
    files.add(root/'scenarios/zona1/experiments/final-20261104-24h-v3.json')
    from simz1_scale_contract import BASE_INPUTS, RANDOM_POLICY, DIAGNOSTIC_SPEC, ORIGIN_SPEC, ORIGIN_POLICY
    files.add(root/RANDOM_POLICY)
    files.add(root/DIAGNOSTIC_SPEC)
    files.add(root/ORIGIN_SPEC)
    files.add(root/ORIGIN_POLICY)
    from simz1_scale_contract import TRANSIT_SPEC, TRANSIT_SERVICE, TRANSIT_BUNDLE
    files.update(root/name for name in (TRANSIT_SPEC, TRANSIT_SERVICE, TRANSIT_BUNDLE))
    files.update(root/name for name in BASE_INPUTS.values())
    # Referenced L18 source network, OSM, freight, lanes and signals are physical dependencies.
    files.update(p for p in variant.rglob('*') if p.is_file() and p.suffix in ('.xml','.json','.osm','.geojson'))
    # The exact source/history treatment is part of the approved routing revision.
    contract = root/'src/main/resources/simz1/osm-sequences-v1.json'
    if contract.is_file():
        files.update(root/name for name in json.loads(contract.read_bytes())['sources'])
    files.add(root/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/Restriction17478998Probe.java')
    from simz1_history_fixtures import REQUIRED_HISTORY_FILES
    files.update(root/name for name in REQUIRED_HISTORY_FILES)
    return sorted(files)


def fingerprint(root=PROJECT):
    root=Path(root)
    digest=hashlib.sha256()
    for path in fingerprint_files(root):
        if not path.is_file():raise ValueError('Required source absent: '+str(path))
        digest.update(path.relative_to(root).as_posix().encode()+b'\0'+sha(path).encode()+b'\n')
    return digest.hexdigest()

def trial_experiment_identity(manifest, od_identity):
    from simz1_scale_contract import experiment, TRIAL_SPEC, ORIGIN_SPEC, ORIGIN_SCHEMA, FREIGHT_SPEC, FREIGHT_SCHEMA, TRANSIT_SPEC, TRANSIT_SCHEMA
    selected = manifest.get('experiment') or {}
    # Only these known contracts choose the trial. Never resolve an arbitrary
    # path supplied by a manifest, or reinterpret a historical v3 acceptance.
    trial_spec = (TRANSIT_SPEC if selected.get('schema') == TRANSIT_SCHEMA else
                  FREIGHT_SPEC if selected.get('schema') == FREIGHT_SCHEMA else
                  ORIGIN_SPEC if selected.get('schema') == ORIGIN_SCHEMA else TRIAL_SPEC)
    expected = experiment(PROJECT/trial_spec, 'run1000')
    if od_identity.get('od_mode') != 'balanced-gateway-v1':
        raise ValueError('Network cannot approve the balanced 24h experiment')
    keys = ('schema','scenario','specification_sha256','base_scenario_identity','base_inputs',
            'total_non_public_vehicles','iterations','demand_seed','service_date','public_vehicles',
            'observation_policy','observation_end_seconds','native_qsim_end_seconds')
    if any(selected.get(k) != expected[k] for k in keys):
        raise ValueError('Trial is not the versioned run1000 of the requested 24h base scenario')
    if (selected.get('origin_admission_policy') != expected.get('origin_admission_policy') or
            selected.get('freight_completion_policy') != expected.get('freight_completion_policy') or
            selected.get('freight_timing_policy') != expected.get('freight_timing_policy')):
        raise ValueError('Trial origin admission policy differs from its versioned base')
    horizon = manifest.get('time_horizon', {})
    iterations = manifest.get('iterations', {})
    if (horizon.get('start_seconds') != 0 or horizon.get('end_seconds') != 86400 or
            manifest.get('demand_seed') != expected['demand_seed'] or
            manifest.get('matsim_seed') != expected['demand_seed'] or
            any(iterations.get(k) != v for k,v in dict(first=0,last=0,requested=1,completed=[0]).items())):
        raise ValueError('Trial native horizon or seeds differ from the experiment')
    return expected['base_scenario_identity']


def inspect(run, expected_people=None, require_transit=True):
    run=Path(run).resolve();manifest_path=run/'run-manifest.json'
    m=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if m.get('status')!='completed' or m.get('validation',{}).get('status')!='valid':raise ValueError('Run not completed/valid')
    if Path(m['folder']).resolve()!=run:raise ValueError('Run folder mismatch')
    n=m['counts']['planned_persons']
    composition = m.get('demand_composition')
    acceptance_n = n
    if composition is not None:
        from simz1_demand_composition import split
        from simz1_agent_types import load_catalog
        from simz1_run import checked_path
        catalog = load_catalog(checked_path(run, m['agent_configuration']['catalog_artifact']))
        expected = split(composition['total_non_public_vehicles'], catalog)
        if (any(composition.get(k) != v for k, v in expected.items()) or
                n != expected['private_vehicles'] or
                m['counts'].get('freight_vehicles_configured') != expected['freight_vehicles'] or
                m['counts'].get('non_public_vehicles_configured') != expected['total_non_public_vehicles']):
            raise ValueError('Trial non-public composition/counts inconsistent')
        acceptance_n = expected['total_non_public_vehicles']
    if expected_people is not None and acceptance_n != expected_people:
        raise ValueError(f'Expected {expected_people} vehicles in trial denominator; observed {acceptance_n}')
    iteration=m['iterations']['last']
    result=m['results'][str(iteration)]
    quality=run/'analysis'/f'it.{iteration}'/'graficas_perfiles/calidad_resultados.json'
    q=json.loads(quality.read_text(encoding='utf-8-sig'))
    allowed_quality = ('screening_pass','not_applicable_no_private_demand') if acceptance_n == 0 else ('screening_pass',)
    if q.get('run_id')!=m['run_id'] or q.get('iteration')!=iteration or q.get('status') not in allowed_quality:
        raise ValueError('Road quality does not pass for this run/iteration; preserve diagnostics')
    public=result.get('public_transport_events',{})
    from simz1_day_observation import enabled as fixed_day
    day=fixed_day(m)
    if day:
        observed_day=result.get('day_observation',{})
        if (observed_day.get('technical_integrity')!='verified_precleanup_census' or
                observed_day.get('coverage_end_seconds')!=86400):raise ValueError('Unverified fixed-day census')
        from simz1_run import checked_path
        checked_path(run,observed_day['census'])
    freight=m.get('freight_transport',{})
    if freight.get('enabled'):
        observed=result.get('freight_transport_events',{})
        from simz1_freight_completion import EXPERIMENTAL_POLICIES
        timing_approved = (observed.get('experimental_acceptance') == 'satisfied'
            if freight.get('completion_policy') in EXPERIMENTAL_POLICIES else observed.get('restricted_window_violations') == 0)
        if (observed.get('status') != 'valid' or not day and (observed.get('vehicles_observed')!=freight['vehicles_configured'] or
                observed.get('arrivals_observed')!=freight['departures_scheduled'] or not timing_approved)):
            raise ValueError('Freight service missing/incomplete or restriction violated; do not scale')
        if freight.get('service_version') == 'weekday-compact-v3':
            from simz1_freight_gateways import POLICY
            gateway = observed.get('native_gateway', {})
            number = freight['vehicles_configured']
            if (gateway.get('policy') != POLICY or gateway.get('required_vehicles')!=number or
                    gateway.get('entry_evidence_count')!=observed.get('vehicles_observed') or gateway.get('exit_evidence_count')!=observed.get('arrivals_observed') or
                    not day and (gateway.get('complete') is not True or
                    any(gateway.get(k) != number for k in ('entry_evidence_count', 'exit_evidence_count')))):
                raise ValueError('Compact freight lacks complete native perimeter body-clearance evidence; do not scale')
    if require_transit:
        fleet = verified_weekday_fleet(run, m, n)
        expected_buses = fleet['public_transport_vehicles_configured']
        expected_ids = fleet['fleet_vehicle_ids']
        if (public.get('public_transport_vehicles_configured') != expected_buses or
                m['counts'].get('public_transport_vehicles_configured') != expected_buses):
            raise ValueError('Public fleet counts differ from this run saved service')
        if composition is not None and m['counts'].get('all_vehicles_configured') != acceptance_n + expected_buses:
            raise ValueError('Total configured vehicles differs from non-public N plus saved public fleet')
        if public.get('road_demand_persons')!=n or public.get('transit_drivers_added_to_demand')!=0:
            raise ValueError('Public fleet mixed with road people')
        if not day and (public.get('transit_drivers_internal_observed') != expected_buses or
                public.get('observed_expedition_starts', 0) < expected_buses):
            raise ValueError('Not all configured buses have an observed dispatch; configuration alone is insufficient')
        observed_ids = public.get('public_transport_vehicle_ids_observed')
        traffic_ids = public.get('public_transport_vehicle_ids_in_traffic')
        if observed_ids is None or traffic_ids is None:
            # Older summaries lacked distinct bus IDs. Read their pinned native
            # evidence, never today's service configuration or invented IDs.
            from simz1_run import checked_path, xml_elements
            dispatched, entered = set(), set()
            expected_set = set(expected_ids)
            for event in xml_elements(checked_path(run, result['events']), 'event', 'events'):
                if event.get('type') == 'TransitDriverStarts':
                    dispatched.add(event.get('vehicleId'))
                elif event.get('type') == 'vehicle enters traffic' and event.get('vehicle') in expected_set:
                    entered.add(event.get('vehicle'))
            if observed_ids is None:
                observed_ids = sorted(dispatched)
            if traffic_ids is None:
                traffic_ids = sorted(entered)
        if (not set(observed_ids).issubset(expected_ids) or not set(traffic_ids).issubset(expected_ids) or
                not day and (observed_ids != expected_ids or traffic_ids != expected_ids)):
            raise ValueError('Distinct observed public vehicles differ from saved fleet; all buses must circulate')
        if not day and public.get('peak_active_public_vehicles_network',0)<1:
            raise ValueError('No native bus traffic observed')
        if not day and public.get('active_public_vehicles_network',0)!=0:
            raise ValueError('Public vehicles remain in the network at the horizon; inspect congestion before scaling')
        trips=public.get('trips',{})
        if trips.get('aborted_before_horizon',0) or not day and trips.get('completed_trips',0)<1:
            raise ValueError('Public-trip outcomes require review')
    from simz1_balanced_launch import manifest_identity
    od_identity = manifest_identity(m)
    if od_identity['od_mode'] == 'balanced-gateway-v1':
        require_balanced_validation()
        from simz1_balanced_od_audit import validate_manifest, require_native_success
        require_native_success(m)
        from revalidar_simz1 import recovery_compatibility
        compatibility = recovery_compatibility(run, m, allow_reviewed_postprocessing=True)
        if compatibility is None:
            validate_manifest(run, m)
        else:
            validate_manifest(run, m, implementation_compatibility=compatibility)
        private = result.get('private_od_events', {})
        if (private.get('evidence_status') != 'closed_native_event_stream' or
                private.get('source', {}).get('run_id') != m['run_id'] or
                private.get('source', {}).get('events') != result.get('events')):
            raise ValueError('Trial lacks closed private OD evidence from this run/events')
        from simz1_run import checked_path
        for key in ('events','plans','network'):
            checked_path(run,result[key])
    experiment_identity = None
    from simz1_scale_contract import ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA
    if (m.get('experiment') or {}).get('schema') in ('simz1-final-experiments-v3', ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        experiment_identity = trial_experiment_identity(m, od_identity)
    return dict(run_directory=str(run),run_id=m['run_id'],iteration=iteration,road_persons=n, od_identity=od_identity,
                base_scenario_identity=experiment_identity,
                catalog_sha256=m.get('agent_configuration',{}).get('catalog_artifact',{}).get('sha256'),
                destination_policy=m.get('destination_policy','legacy-gaussian-v1'),
                signal_coordination_policy=m.get('short_link_signal_coordination',{}).get('policy','none'),
                freight_service_version=freight.get('service_version'),
                freight_service_sha256=freight.get('source_service_sha256'),
                acceptance_vehicles=acceptance_n, acceptance_denominator='non_public_vehicles' if composition else 'private_persons',
                manifest_sha256=sha(manifest_path),quality_sha256=sha(quality),public_transport=public,
                status='accepted_for_next_load_test_not_calibrated')

def verify_preparation_identity(spec, scenario, request, source_fingerprint, postprocessing_policy=None):
    """Exercise the real specification pin/rebuild boundary without population.

    The temporary directory contains only the experiment specification. It is
    removed before returning; no scenario, plans or run manifest is created.
    """
    import re
    import tempfile
    from generate_montecarlo_z1 import pin_experiment_specification
    from simz1_scale_contract import experiment, verify_launch_request, launch_postprocessing_policy, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA
    if (not isinstance(source_fingerprint, str) or
            not re.fullmatch('[a-f0-9]{64}', source_fingerprint) or
            source_fingerprint != fingerprint()):
        raise ValueError('Preparation identity source fingerprint differs from current revision')
    if (not isinstance(request, dict) or
            not isinstance(request.get('launch_id'), str) or
            not re.fullmatch('[a-f0-9]{32}', request['launch_id']) or
            type(request.get('dry_run')) is not bool):
        raise ValueError('Preparation identity requires an explicit launch request')
    selected = experiment(spec, scenario)
    policy = launch_postprocessing_policy(selected, postprocessing_policy)
    if request.get('postprocessing_policy') != policy:
        raise ValueError('Preparation request postprocessing policy differs from the explicit launch')
    verify_launch_request(request, selected)
    with tempfile.TemporaryDirectory(prefix='simz1-preparation-identity-') as temporary:
        pinned = pin_experiment_specification(spec,
            Path(temporary)/'experiment-specification.json', request['experiment'])
        rebuilt = experiment(pinned, scenario)
        # This is the same full comparison used by the native manifest audit;
        # the copied path is the only v5 field allowed to differ.
        verify_launch_request(request, rebuilt)
        copied_sha256 = sha(pinned)
    if source_fingerprint != fingerprint():
        raise ValueError('Preparation identity sources changed during verification')
    physical = {}
    if selected.get('schema') in (ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        from simz1_configuration_contract import expected_from_selection
        physical['configuration'] = expected_from_selection(selected)
    return dict(schema='simz1-preparation-identity-v2', status='verified',
        launch_id=request['launch_id'], dry_run=request['dry_run'],
        source_fingerprint=source_fingerprint, experiment=selected, postprocessing_policy=policy,
        copied_specification_sha256=copied_sha256,
        verification='generator_pin_and_rebuild_full_selection_v1', **physical)


def require_preparation_identity(directory, state, request, selected, source_fingerprint, postprocessing_policy=None):
    """A load DryRun binds preparation, physical identity and postprocessing scope."""
    from simz1_scale_contract import verify_selection_identity, launch_postprocessing_policy, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA
    policy = launch_postprocessing_policy(selected, postprocessing_policy)
    if request.get('postprocessing_policy') != policy or state.get('postprocessing_policy') != policy:
        raise ValueError('DryRun postprocessing policy differs from the requested Run')
    path = Path(directory)/'preparation-identity.json'
    if state.get('preparation_identity_sha256') != sha(path):
        raise ValueError('DryRun preparation identity receipt hash differs')
    receipt = json.loads(path.read_text(encoding='utf-8-sig'))
    expected = dict(schema='simz1-preparation-identity-v2', status='verified',
        launch_id=request['launch_id'], dry_run=True,
        source_fingerprint=source_fingerprint, postprocessing_policy=policy,
        copied_specification_sha256=selected['specification_sha256'],
        verification='generator_pin_and_rebuild_full_selection_v1')
    if selected.get('schema') in (ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        from simz1_configuration_contract import expected_from_selection
        expected['configuration'] = expected_from_selection(selected)
    if (not isinstance(receipt, dict) or receipt.get('dry_run') is not True or
            {k:v for k,v in receipt.items() if k != 'experiment'} != expected):
        raise ValueError('DryRun preparation identity receipt differs from current selection or revision')
    verify_selection_identity(receipt.get('experiment'), selected)


def require_experiment_dry_run(spec, scenario, launch_id, postprocessing_policy=None):
    """Bind Run to an explicit successful DryRun of the same versioned selection."""
    import re
    from simz1_scale_contract import experiment, RANDOM_SCHEMA, DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA, verify_launch_request
    if not isinstance(launch_id, str) or not re.fullmatch('[a-f0-9]{32}', launch_id):
        raise ValueError('Run requires an explicit DryRun LaunchId')
    selected = experiment(spec, scenario)
    # experiment() already validates the complete versioned selector document.
    # Bind every compatible selector to its actual authorized iteration count;
    # a folder name or population size must not select a different gate.
    supported = selected.get('schema') in (RANDOM_SCHEMA, DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA,
                                           'simz1-final-experiments-v3')
    if not supported:
        raise ValueError('This gate requires an authorized versioned load experiment')
    directory = PROJECT/'runtime/launches'/launch_id
    state = json.loads((directory/'state.json').read_text(encoding='utf-8-sig'))
    request = json.loads((directory/'request.json').read_text(encoding='utf-8-sig'))
    verify_launch_request(request, selected)
    current_fingerprint = fingerprint()
    if (state.get('launch_id') != launch_id or request.get('launch_id') != launch_id or
            state.get('dry_run') is not True or request.get('dry_run') is not True or
            state.get('status') != 'dry_run_pass' or state.get('phase') != 'completed' or
            state.get('outcome') != 'PASSED' or state.get('exit_code') != 0 or
            state.get('run_launch_eligible') is not True or
            state.get('prior_trial_status') != ('not_applicable_this_is_trial'
                if selected.get('scenario') == 'run1000' else 'accepted_same_base_and_revision') or
            state.get('source_fingerprint') != current_fingerprint or state.get('run_id') is not None):
        raise ValueError('DryRun does not approve the same selection, base and current revision')
    require_preparation_identity(directory, state, request, selected, current_fingerprint,
                                 postprocessing_policy)
    return launch_id


def _publish_inspected_trial(record, state_path, inspected_fingerprint, *, launch_recovery=None):
    """Internal publication after inspect; reject evidence/revision races."""
    record=dict(record);run=Path(record['run_directory'])
    quality=run/'analysis'/f"it.{record['iteration']}"/'graficas_perfiles/calidad_resultados.json'
    if (sha(run/'run-manifest.json')!=record['manifest_sha256'] or
            sha(quality)!=record['quality_sha256'] or fingerprint()!=inspected_fingerprint):
        raise ValueError('Inspected trial or sources changed before publication')
    record['source_fingerprint']=inspected_fingerprint
    if launch_recovery is not None:
        record['launch_recovery']=launch_recovery
    state_path=Path(state_path)
    state_path.parent.mkdir(parents=True,exist_ok=True)
    tmp=state_path.with_suffix('.tmp');tmp.write_text(json.dumps(record,indent=2),encoding='utf-8');tmp.replace(state_path)
    return record


def record_trial(run_dir, state_path, *, launch_recovery=None):
    """Publish only the official inspector's result for the current revision."""
    revision=fingerprint();record=inspect(run_dir,1000)
    return _publish_inspected_trial(record,state_path,revision,launch_recovery=launch_recovery)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('record-trial','require-trial','require-balanced-validation','verify-preparation-identity','require-experiment-dry-run','path','fingerprint'))
    p.add_argument('--run-dir',type=Path);p.add_argument('--state',type=Path,default=PROJECT/'runtime/workflow/trial.json')
    p.add_argument("--catalog-sha256");p.add_argument("--destination-policy")
    p.add_argument('--signal-coordination-policy')
    p.add_argument('--freight-service-version');p.add_argument('--freight-service-sha256')
    p.add_argument('--od-mode', choices=('network','balanced-gateway-v1'))
    p.add_argument('--zone-boundary', type=Path);p.add_argument('--od-access-catalog', type=Path)
    p.add_argument('--od-mix-file', type=Path)
    p.add_argument('--experiment-spec', type=Path);p.add_argument('--experiment-scenario')
    p.add_argument('--dry-run-launch-id')
    p.add_argument('--launch-request', type=Path);p.add_argument('--source-fingerprint')
    p.add_argument('--postprocessing-policy')
    a=p.parse_args(argv)
    try:
        if a.action=='fingerprint':print(fingerprint());return 0
        if a.action=='verify-preparation-identity':
            if a.launch_request is None:raise ValueError('--launch-request required')
            request=json.loads(a.launch_request.read_text(encoding='utf-8-sig'))
            receipt=verify_preparation_identity(a.experiment_spec,a.experiment_scenario,
                                               request,a.source_fingerprint,a.postprocessing_policy)
            print(json.dumps(receipt,indent=2));return 0
        if a.action=='require-experiment-dry-run':
            print('SAME_SELECTION_DRY_RUN_ACCEPTED '+require_experiment_dry_run(a.experiment_spec,a.experiment_scenario,a.dry_run_launch_id,a.postprocessing_policy))
            return 0
        if a.action=='require-balanced-validation':
            require_balanced_validation()
            print('INTEGRATED_VALIDATE_ACCEPTED; no trial approval created')
            return 0
        if a.action=='record-trial':
            if a.run_dir is None:raise ValueError('--run-dir required')
            record=record_trial(a.run_dir,a.state)
            print(json.dumps(record,indent=2));return 0
        stored=json.loads(a.state.read_text(encoding='utf-8-sig'))
        if a.action=='path':
            if not Path(stored['run_directory']).is_dir():raise ValueError('Recorded run no longer exists')
            print(stored['run_directory']);return 0
        if stored.get('launch_recovery') is not None:
            from simz1_launch_recovery import require_recovery_receipt
            require_recovery_receipt(stored,root=PROJECT)
        current=inspect(stored['run_directory'],1000)
        if any(stored.get(k)!=current.get(k) for k in ('manifest_sha256','quality_sha256','run_id')):
            raise ValueError('Accepted trial files changed')
        if stored.get('source_fingerprint')!=fingerprint():raise ValueError('Code/config changed since trial; repeat 1,000-person acceptance')
        if a.catalog_sha256 and current.get('catalog_sha256')!=a.catalog_sha256:raise ValueError('Trial catalog differs from requested scenario')
        if a.destination_policy and current.get('destination_policy')!=a.destination_policy:raise ValueError('Trial destination policy differs from requested scenario')
        if a.signal_coordination_policy and current.get('signal_coordination_policy')!=a.signal_coordination_policy:raise ValueError('Trial signal coordination differs from requested scenario')
        if a.freight_service_version and current.get('freight_service_version')!=a.freight_service_version:raise ValueError('Trial freight version differs from requested scenario')
        if a.freight_service_sha256 and current.get('freight_service_sha256')!=a.freight_service_sha256:raise ValueError('Trial freight service differs from requested scenario')
        if a.experiment_spec:
            from simz1_scale_contract import experiment
            requested = experiment(a.experiment_spec, a.experiment_scenario)
            if not requested.get('base_scenario_identity') or current.get('base_scenario_identity') != requested['base_scenario_identity']:
                raise ValueError('Trial lacks the same versioned 24h base scenario; historical/network trials cannot approve it')
        elif a.experiment_scenario:
            raise ValueError('Experiment scenario requires its specification')
        if a.od_mode:
            if current['od_identity']['od_mode'] != a.od_mode:
                raise ValueError('Trial OD mode differs; network cannot approve balanced-gateway-v1')
            if a.od_mode == 'balanced-gateway-v1':
                from simz1_balanced_launch import identity
                if current['od_identity'] != identity(a.zone_boundary,a.od_access_catalog,a.od_mix_file):
                    raise ValueError('Trial perimeter/access/hypothesis differs from requested balanced OD')
        print('TRIAL_1000_ACCEPTED '+stored['run_id']);return 0
    except (OSError,ValueError,KeyError,TypeError) as e:
        print('Workflow blocked: '+str(e),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
