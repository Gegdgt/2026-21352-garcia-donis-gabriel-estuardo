"""Versioned, exact opt-in balanced scale contract; no generation or execution."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import stat
import uuid
from datetime import datetime, timezone

BALANCED_TOTALS = (1000, 110000, 180000)
EXPERIMENT_SCHEMA='simz1-final-experiments-v1'
DRAW_SEED='SIMZ1-final-20261102-N-v1'
PROJECT = Path(__file__).resolve().parents[1]
TRIAL_SPEC = 'scenarios/zona1/experiments/final-20261104-24h-v3.json'
RANDOM_SCHEMA = 'simz1-final-experiments-v4'
RANDOM_POLICY = 'scenarios/zona1/experiments/final-20261105-random-24h-v4.json'
RANDOM_SCENARIO = 'random-full-1'
DIAGNOSTIC_SCHEMA = 'simz1-final-experiments-v5'
DIAGNOSTIC_SPEC = 'scenarios/zona1/experiments/final-20261105-run10k-24h-v5.json'
DIAGNOSTIC_SCENARIO = 'run10000'
ORIGIN_SCHEMA = 'simz1-final-experiments-v6'
ORIGIN_SPEC = 'scenarios/zona1/experiments/final-20261106-origin-gap-24h-v6.json'
ORIGIN_POLICY = 'src/main/resources/simz1/origin-admission-v1.json'
FREIGHT_SCHEMA = 'simz1-final-experiments-v7'
FREIGHT_SPEC = 'scenarios/zona1/experiments/final-20261108-freight-entry-24h-v7.json'
FREIGHT_POLICY = 'src/main/resources/simz1/freight-entry-completion-v2.json'
TRANSIT_SCHEMA = 'simz1-final-experiments-v8'
TRANSIT_SPEC = 'scenarios/zona1/experiments/final-20261108-transit-service-24h-v8.json'
TRANSIT_SERVICE = 'scenarios/zona1/transit/weekday-v2/service-fleet-176-93-v8.json'
TRANSIT_BUNDLE = 'scenarios/zona1/transit/weekday-v2/route-bundle-service-v8.json'
LEGACY_ORIGIN_POLICY = 'empty-slot-origin-v1'
GAP_ORIGIN_POLICY = 'physical-gap-origin-v1'
SELECTION_ROOT = PROJECT/'runtime/experiment-selections'
BASE_INPUTS = dict(
    source_config='scenarios/zona1/od/balanced-gateway-v1/access-review-v2/config-l18-local-v1.xml',
    agent_catalog='scenarios/zona1/agent-types-balanced-v1.json',
    transit_service='scenarios/zona1/transit/weekday-v2/service-fleet-176-93-v1.json',
    freight_service='scenarios/zona1/od/balanced-gateway-v1/access-review-v2/freight/service-composition-v3.json',
    zone_boundary='scenarios/zona1/od/balanced-gateway-v1/perimeter.geojson',
    od_access_catalog='scenarios/zona1/od/balanced-gateway-v1/access.json',
    od_mix_file='scenarios/zona1/od/balanced-gateway-v1/mix.json',
    day_policy='src/main/resources/simz1/day-observation-v1.json')


def draw_total(seed=DRAW_SEED):
    """Independent SHA256 rejection sampling of one inclusive integer."""
    span=40001; ceiling=(2**256//span)*span
    for counter in range(1000):
        raw=hashlib.sha256((seed+':'+str(counter)).encode('utf-8')).hexdigest()
        value=int(raw,16)
        if value<ceiling:return 180000+value%span,dict(seed=seed,algorithm='sha256-rejection-u256be-v1',counter=counter,sha256=raw,inclusive_range=[180000,220000])
    raise ValueError('Unresolved experiment draw')


def specification():
    n,draw=draw_total()
    return dict(schema=EXPERIMENT_SCHEMA,draw=dict(draw,selected_non_public_vehicles=n),
        demand_seed=20261023,service_date='2026-10-23',public_vehicles=269,
        freight_completion_policy='freight-close-plus3600-v1',demand_end_seconds=86400,observation_end_seconds=108000,
        signal_variant='l18-local-synthetic-offsets-v1',
        scenarios={key:dict(total_non_public_vehicles=total,iterations=iterations,population_group=group)
            for key,total,iterations,group in [('buses',0,1,'buses'),('half',110000,1,'half'),('quarter',55000,1,'quarter'),
                ('full-1',n,1,'full-shared'),('full-10',n,10,'full-shared'),('max-test',220000,1,'max-test')]})


def experiment(path, scenario):
    path=Path(path).resolve(strict=True)
    doc=json.loads(path.read_text(encoding='utf-8-sig'))
    random = doc.get('schema') == RANDOM_SCHEMA
    if random:
        selection = validate_random_specification(doc)
    elif doc.get('schema') == TRANSIT_SCHEMA:
        if _json_bytes(doc) != _json_bytes(transit_specification()):
            raise ValueError('Transit-service experiment differs from the authorized fixed selection')
    elif doc.get('schema') == FREIGHT_SCHEMA:
        if _json_bytes(doc) != _json_bytes(freight_specification()):
            raise ValueError('Freight-timing experiment differs from the authorized fixed selection')
    elif doc.get('schema') == ORIGIN_SCHEMA:
        if _json_bytes(doc) != _json_bytes(origin_specification()):
            raise ValueError('Origin-policy experiment differs from the authorized fixed selection')
    elif doc.get('schema') == DIAGNOSTIC_SCHEMA:
        if _json_bytes(doc) != _json_bytes(diagnostic_specification()):
            raise ValueError('Diagnostic experiment differs from the authorized fixed selection')
    elif doc not in (specification(), day_specification(), trial_specification()):raise ValueError('Experiment specification differs from the authorized reproducible selection')
    if scenario not in doc['scenarios']:raise ValueError('Unknown authorized experiment scenario')
    from simz1_freight_completion import policy_document
    policy_document(doc['freight_completion_policy'])
    return dict(doc['scenarios'][scenario],scenario=scenario,schema=doc['schema'],
        specification_path=str(path),specification_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        demand_seed=doc['demand_seed'],service_date=doc['service_date'],public_vehicles=doc['public_vehicles'],
        freight_completion_policy=doc['freight_completion_policy'],demand_end_seconds=doc['demand_end_seconds'],
        observation_end_seconds=doc['observation_end_seconds'],draw=doc['draw'],signal_variant=doc['signal_variant'],
        **({k:doc[k] for k in ('observation_policy','native_qsim_end_seconds')} if 'observation_policy' in doc else {}),
        **(dict(base_inputs=doc['base_inputs'], base_scenario_identity=base_identity(doc),
                derived_from=doc['derived_from'], acceptance_trial_scenario='run1000')
           if 'base_inputs' in doc else {}),
        **(dict(postprocessing=doc['postprocessing']) if doc.get('schema') in (DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA) else {}),
        **(dict(origin_admission_policy=doc['origin_admission_policy']) if doc.get('schema') in (ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA) else {}),
        **(dict(freight_timing_policy=doc['freight_timing_policy']) if doc.get('schema') in (FREIGHT_SCHEMA, TRANSIT_SCHEMA) else {}),
        **(dict(selection=selection, selection_sha256=doc['selection_sha256'],
                selection_path=str(SELECTION_ROOT/selection['selection_id']/'selection.json')) if random else {}))


def day_specification():
    from simz1_day_observation import policy_document
    policy=policy_document()
    doc=specification()  # Preserve the original draw, roster, seed and selectors.
    doc.update(schema='simz1-final-experiments-v2', observation_policy=policy['version'],
        observation_end_seconds=policy['observation_end_seconds'],
        native_qsim_end_seconds=policy['native_qsim_end_seconds'])
    return doc


def trial_specification():
    """Versioned successor; the previous draw and all six selectors stay intact."""
    previous = 'scenarios/zona1/experiments/final-20261103-24h-v2.json'
    raw = (PROJECT/previous).read_bytes()
    if json.loads(raw) != day_specification():
        raise ValueError('Historical 24h specification changed')
    doc = day_specification()
    doc.update(schema='simz1-final-experiments-v3',
               derived_from=dict(path=previous, sha256=hashlib.sha256(raw).hexdigest()),
               base_inputs=dict(BASE_INPUTS), acceptance_trial_scenario='run1000',
               trial_difference='N and its composition quotas only; same physical sources and daily policies')
    doc['scenarios']['run1000'] = dict(total_non_public_vehicles=1000, iterations=1, population_group='run1000')
    return doc


def diagnostic_specification():
    """Fixed Run10K successor; neither draws entropy nor changes the trial size."""
    previous = PROJECT/TRIAL_SPEC
    raw = previous.read_bytes()
    if json.loads(raw) != trial_specification():
        raise ValueError('Historical trial specification changed')
    doc = trial_specification()
    doc.update(schema=DIAGNOSTIC_SCHEMA,
        derived_from=dict(path=TRIAL_SPEC, sha256=hashlib.sha256(raw).hexdigest()),
        draw=dict(algorithm='fixed-no-draw-v1', selected_non_public_vehicles=10000),
        postprocessing=dict(policy='native_diagnostic_v1',
            replay_preparation='manual_after_native_validation',
            visual_acceptance='separate_not_certified_by_native_gate'),
        scenarios={DIAGNOSTIC_SCENARIO:dict(total_non_public_vehicles=10000,
            iterations=1, population_group=DIAGNOSTIC_SCENARIO,
            composition=dict(carro=4400, moto=5500, pesado=100, public_transport=269))})
    return doc


def origin_policy_specification():
    """Exact opt-in contract; this describes no new lane, flow or storage capacity."""
    return dict(schema='simz1-origin-admission-policy-v1', version=GAP_ORIGIN_POLICY,
        legacy_policy=LEGACY_ORIGIN_POLICY, default_policy=LEGACY_ORIGIN_POLICY,
        mechanism_ids=[1, 2, 5], insertion_anchor='native_original_queue_buffer_endpoint',
        minimum_body_gap_m=0.10, nominal_lane_width_m=3.0,
        full_body_support=True, route_occurrence_and_reach_required=True,
        explicit_direct_original_terminal_connectivity=True,
        represented_original_lane_count_matches_domain=True,
        finite_positive_body_and_pcu=True,
        preserve_committed_anchor_on_reroute=True,
        bilateral_clearance=True, overtake_existing_body=False,
        fifo='existing_shared_origin_waiting_list_head',
        flow='native_pcu_credit_debt_single_debit',
        storage='native_activity_buffer_and_corridor_body_reservations',
        offer='pure_geometry_then_revalidated_serial_origin_commit',
        required=dict(storage_policy='strict-receiver-v1', whole_vehicle_reservation=True,
                      qsim_threads=1, traffic_dynamics='queue', link_dynamics='FIFO'),
        legacy_fallbacks=['bus', 'null_driver', 'terminal', 'short_origin', 'passage',
                          'unmanaged_origin', 'unrepresented_original', 'unrepresented_movement',
                          'complex_or_mixed_topology', 'representation_mismatch'],
        adds_capacity=False, changes_departure_schedule=False,
        changes_network_signals_bodies_or_fixed_services=False)


def origin_policy_identity():
    path = PROJECT/ORIGIN_POLICY
    raw = path.read_bytes()
    if _json_bytes(json.loads(raw)) != _json_bytes(origin_policy_specification()):
        raise ValueError('Origin admission policy differs from the versioned physical contract')
    return dict(version=GAP_ORIGIN_POLICY, policy_path=ORIGIN_POLICY,
                policy_sha256=hashlib.sha256(raw).hexdigest())


def origin_policy_for_selection(selected):
    """An old/absent experiment always retains the former origin behavior."""
    if not selected or selected.get('schema') not in (ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        if selected and 'origin_admission_policy' in selected:
            raise ValueError('Origin admission policy requires its explicit versioned experiment')
        return LEGACY_ORIGIN_POLICY
    if selected.get('origin_admission_policy') != origin_policy_identity():
        raise ValueError('Selected origin admission policy differs')
    return GAP_ORIGIN_POLICY


def origin_specification():
    """Four fixed scales of one new policy, retaining the historical v3/v5 contracts."""
    previous = PROJECT/TRIAL_SPEC
    raw = previous.read_bytes()
    if json.loads(raw) != trial_specification():
        raise ValueError('Historical trial specification changed')
    doc = trial_specification()
    totals = (1000, 10000, 55000, 110000)
    doc.update(schema=ORIGIN_SCHEMA,
        derived_from=dict(path=TRIAL_SPEC, sha256=hashlib.sha256(raw).hexdigest()),
        origin_admission_policy=origin_policy_identity(),
        draw=dict(algorithm='fixed-staged-no-draw-v1', authorized_non_public_totals=list(totals)),
        trial_difference='N and its composition quotas only; same explicitly selected origin policy and daily physical base',
        postprocessing=dict(policy='native_diagnostic_v1',
            replay_preparation='manual_after_native_validation',
            visual_acceptance='separate_not_certified_by_native_gate'),
        scenarios={'run'+str(n): dict(total_non_public_vehicles=n, iterations=1,
            population_group='origin-gap-'+str(n),
            composition=dict(carro=n*44//100, moto=n*55//100, pesado=n//100,
                             public_transport=269)) for n in totals})
    return doc


def freight_policy_identity():
    """Bind the authorized v2 timing resource without reinterpreting historical v1."""
    from simz1_freight_completion import policy_document, TOLERATED_ENTRY_POLICY
    path = PROJECT/FREIGHT_POLICY
    raw = path.read_bytes()
    if _json_bytes(json.loads(raw)) != _json_bytes(policy_document(TOLERATED_ENTRY_POLICY)):
        raise ValueError('Freight timing policy differs from the authorized contract')
    return dict(version=TOLERATED_ENTRY_POLICY, policy_path=FREIGHT_POLICY,
                policy_sha256=hashlib.sha256(raw).hexdigest())


def freight_specification():
    """Explicit successor: entry and completion share close+3600; all demand stays fixed."""
    raw = (PROJECT/ORIGIN_SPEC).read_bytes()
    if _json_bytes(json.loads(raw)) != _json_bytes(origin_specification()):
        raise ValueError('Historical origin-policy specification changed')
    doc = json.loads(raw)
    policy = freight_policy_identity()
    doc.update(schema=FREIGHT_SCHEMA,
        derived_from=dict(path=ORIGIN_SPEC, sha256=hashlib.sha256(raw).hexdigest()),
        freight_completion_policy=policy['version'], freight_timing_policy=policy,
        trial_difference='N and its composition quotas only; same origin policy and authorized freight entry/completion deadline',
        change_scope='Freight may enter until its original nominal close plus 3600 seconds inclusive; completion deadline unchanged; no schedule, geometry, OD, physical admission or horizon change')
    return doc


def transit_specification():
    """Authorized v8: L12 terminal recovery; mixed Plaza infrastructure retained."""
    raw = (PROJECT/FREIGHT_SPEC).read_bytes()
    if _json_bytes(json.loads(raw)) != _json_bytes(freight_specification()):
        raise ValueError('Historical freight-policy specification changed')
    doc = json.loads(raw)
    totals = (1000, 10000, 55000)
    doc.update(schema=TRANSIT_SCHEMA,
        derived_from=dict(path=FREIGHT_SPEC, sha256=hashlib.sha256(raw).hexdigest()),
        draw=dict(algorithm='fixed-staged-no-draw-v1', authorized_non_public_totals=list(totals)),
        scenarios={key:value for key,value in doc['scenarios'].items()
                   if key in ('run1000','run10000','run55000')},
        trial_difference='N and its composition quotas only; same v8 transit service, mixed Plaza lanes and physical policies',
        change_scope='L12 terminal transfer_after 180 to 400 seconds at both ends; fleet 269, identities, routes and dwell 25 preserved; Plaza remains mixed, no exclusive lane claimed; private demand, seeds, OD, freight v2 and 24h horizon unchanged')
    doc['base_inputs']['transit_service'] = TRANSIT_SERVICE
    return doc


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True)+'\n').encode('utf-8')


def _sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def random_policy_specification():
    """Authorized policy, not itself a selected population or launch receipt."""
    previous = PROJECT/TRIAL_SPEC
    if json.loads(previous.read_bytes()) != trial_specification():
        raise ValueError('Historical trial specification changed')
    doc = trial_specification()
    doc.pop('draw')
    doc.update(schema='simz1-random-experiment-policy-v1',
        derived_from=dict(path=TRIAL_SPEC, sha256=_sha_bytes(previous.read_bytes())),
        draw_policy=dict(version='system-entropy-single-draw-v1',
                         entropy_source='secrets.token_hex', entropy_bytes=32,
                         algorithm='sha256-rejection-u256be-v1', inclusive_range=[180000,220000],
                         max_attempts=1000, reuse='one selection, one DryRun identity, at most one Run'),
        scenarios={RANDOM_SCENARIO:dict(total_non_public_vehicles='from_immutable_selection',
                                       iterations=1, population_group='random-full')})
    return doc


def _random_policy():
    path = PROJECT/RANDOM_POLICY
    raw = path.read_bytes()
    doc = json.loads(raw)
    if doc != random_policy_specification():
        raise ValueError('Random experiment policy differs from the authorized version')
    return doc, _sha_bytes(raw)


def physical_source_inventory():
    """Bind all versioned physical inputs and native sources, including XML references.

    The workflow inventory already enumerates the reviewed L18 tree, OSM source,
    lanes, signals, service inputs and sequence-contract references. This is an
    additional explicit physical inventory; the complete revision is also bound.
    """
    from simz1_workflow_state import fingerprint_files, sha
    result = {}
    for path in fingerprint_files(PROJECT):
        name = path.relative_to(PROJECT).as_posix()
        if (name.startswith(('src/main/java/', 'src/main/resources/simz1/')) or
                (name.startswith('scenarios/zona1/') and '/experiments/' not in name)):
            if not path.is_file(): raise ValueError('Required physical source absent: '+name)
            result[name] = sha(path)
    return result


def _random_document(receipt, policy, policy_sha):
    # A selected document remains self-contained when pinned into the run inputs.
    # Its separate, exclusively created receipt must still match at every gate.
    doc = dict(policy)
    doc.pop('draw_policy')
    doc.update(schema=RANDOM_SCHEMA,
               random_policy=dict(path=RANDOM_POLICY, sha256=policy_sha),
               selection=receipt, selection_sha256=_sha_bytes(_json_bytes(receipt)),
               draw={k:receipt[k] for k in ('seed','algorithm','counter','sha256',
                                           'inclusive_range','selected_non_public_vehicles')},
               scenarios={RANDOM_SCENARIO:dict(total_non_public_vehicles=receipt['selected_non_public_vehicles'],
                                               iterations=1, population_group='random-full')})
    return doc


def _validate_receipt(receipt, policy_sha, *, verify_sources=True):
    required = {'schema','selection_id','created_utc','entropy_source','entropy_bytes',
                'seed','algorithm','counter','sha256','inclusive_range',
                'selected_non_public_vehicles','rejection_attempts','policy_path','policy_sha256',
                'source_fingerprint','physical_sources','physical_sources_sha256',
                'base_scenario_identity','composition','composition_rounding',
                'demand_seed','service_date','iterations'}
    candidate = isinstance(receipt,dict) and receipt.get('schema') == 'simz1-random-selection-v2'
    if candidate: required.add('candidate_id')
    if not isinstance(receipt,dict) or set(receipt) != required:
        raise ValueError('Random selection receipt has missing or unknown fields')
    if candidate: _require_candidate_id(receipt['candidate_id'])
    if (receipt['schema'] not in ('simz1-random-selection-v1','simz1-random-selection-v2') or
            not re.fullmatch('[0-9a-f]{32}',str(receipt['selection_id'])) or
            uuid.UUID(hex=receipt['selection_id']).version != 4 or
            not re.fullmatch('[0-9a-f]{64}',str(receipt['seed'])) or
            receipt['entropy_source'] != 'secrets.token_hex' or receipt['entropy_bytes'] != 32):
        raise ValueError('Random selection identity or entropy declaration differs')
    try:
        instant = datetime.fromisoformat(receipt['created_utc'])
        if instant.utcoffset() != timezone.utc.utcoffset(instant): raise ValueError()
    except (TypeError,ValueError):
        raise ValueError('Selection time must be an explicit UTC timestamp') from None
    n, draw = draw_total(receipt['seed'])
    if (any(receipt[k] != value for k,value in draw.items()) or
            type(receipt['selected_non_public_vehicles']) is not int or receipt['selected_non_public_vehicles'] != n or
            type(receipt['counter']) is not int or type(receipt['rejection_attempts']) is not int or
            receipt['rejection_attempts'] != draw['counter'] or
            receipt['policy_path'] != RANDOM_POLICY or receipt['policy_sha256'] != policy_sha or
            receipt['demand_seed'] != 20261023 or receipt['service_date'] != '2026-10-23' or
            type(receipt['iterations']) is not int or receipt['iterations'] != 1):
        raise ValueError('Random draw, policy or single-iteration configuration changed')
    if (not re.fullmatch('[0-9a-f]{64}',str(receipt['source_fingerprint'])) or
            not isinstance(receipt['physical_sources'],dict) or not receipt['physical_sources'] or
            any(not re.fullmatch('[0-9a-f]{64}',str(value)) for value in receipt['physical_sources'].values()) or
            receipt['physical_sources_sha256'] != _sha_bytes(_json_bytes(receipt['physical_sources']))):
        raise ValueError('Physical source inventory or revision is invalid')
    from simz1_demand_composition import split
    from simz1_agent_types import load_catalog
    composition = split(n,load_catalog(PROJECT/BASE_INPUTS['agent_catalog']))
    if (receipt['composition'] != dict(composition['family_counts'],public_transport=269) or
            receipt['composition_rounding'] != composition['rounding'] or
            receipt['base_scenario_identity'] != base_identity(trial_specification())):
        raise ValueError('Random selection composition or physical base differs')
    if verify_sources:
        from simz1_workflow_state import fingerprint
        if receipt['source_fingerprint'] != fingerprint():
            raise ValueError('Sources changed after the random selection')
        if receipt['physical_sources'] != physical_source_inventory():
            raise ValueError('Physical sources changed after the random selection')


def validate_random_specification(doc):
    policy, policy_sha = _random_policy()
    receipt = doc.get('selection')
    _validate_receipt(receipt, policy_sha)
    if doc != _random_document(receipt,policy,policy_sha):
        raise ValueError('Selected experiment differs from its immutable authorized draw')
    intent = _draw_intent_path(receipt.get('candidate_id'))
    if intent.is_symlink() or intent.read_bytes() != _json_bytes(_draw_intent(receipt)):
        raise ValueError('Selection differs from the exclusive policy draw intent')
    folder = SELECTION_ROOT/receipt['selection_id']
    raw = (folder/'selection.json').read_bytes()
    digest = _sha_bytes(raw)
    if (raw != _json_bytes(receipt) or digest != doc['selection_sha256'] or
            (folder/'selection.sha256').read_text(encoding='ascii') != digest+'\n'):
        raise ValueError('External immutable selection receipt or checksum differs')
    # The source document cannot be changed and then treated as a new selection.
    if (folder/'experiment.json').read_bytes() != _json_bytes(doc):
        raise ValueError('Original selected experiment differs')
    return receipt


def _exclusive_write(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    Path(path).chmod(stat.S_IREAD)


def _require_candidate_id(candidate_id):
    if (not isinstance(candidate_id,str) or not re.fullmatch('[0-9a-f]{32}',candidate_id) or
            uuid.UUID(hex=candidate_id).version != 4):
        raise ValueError('Candidate identity must be an explicit lowercase UUIDv4 hex value')
    return candidate_id


def _draw_intent_path(candidate_id=None):
    # Legacy --draw retains its one global policy intent. An explicitly named
    # candidate has one separate durable intent across all source revisions.
    # Neither a failed draw nor a revised source permits redrawing that identity.
    if candidate_id is not None:
        return SELECTION_ROOT/'candidates'/(_require_candidate_id(candidate_id)+'.draw-intent.json')
    return SELECTION_ROOT/(Path(RANDOM_POLICY).stem+'.draw-intent.json')


def _draw_intent(receipt):
    candidate_id=receipt.get('candidate_id')
    if candidate_id is not None: _require_candidate_id(candidate_id)
    return dict(schema='simz1-random-draw-intent-v2' if candidate_id is not None else 'simz1-random-draw-intent-v1',
                **{key:receipt[key] for key in ('selection_id','created_utc','policy_path',
                                               'policy_sha256','source_fingerprint')},
                **(dict(candidate_id=candidate_id) if candidate_id is not None else {}))


def create_random_selection(candidate_id=None):
    """One immutable draw per explicit candidate, or the original global policy.

    Never called by DryRun or Run. Merely reading an existing candidate does not
    consume entropy, and another revision cannot repeat the candidate's draw.
    """
    if candidate_id is not None: _require_candidate_id(candidate_id)
    from simz1_workflow_state import fingerprint
    from simz1_demand_composition import split
    from simz1_agent_types import load_catalog
    policy, policy_sha = _random_policy()
    revision = fingerprint()
    sources = physical_source_inventory()
    identity = dict(selection_id=uuid.uuid4().hex, created_utc=datetime.now(timezone.utc).isoformat(),
                    policy_path=RANDOM_POLICY,policy_sha256=policy_sha,source_fingerprint=revision)
    if candidate_id is not None: identity['candidate_id']=candidate_id
    intent_path=_draw_intent_path(candidate_id)
    intent_path.parent.mkdir(parents=True,exist_ok=True)
    _exclusive_write(intent_path,_json_bytes(_draw_intent(identity)))
    folder = SELECTION_ROOT/identity['selection_id']
    folder.mkdir(exist_ok=False)
    # The exclusive intent is durable BEFORE any entropy is requested. It is
    # never removed on error, so interruption cannot turn into another draw.
    seed = secrets.token_hex(32)
    n, draw = draw_total(seed)
    composition = split(n,load_catalog(PROJECT/BASE_INPUTS['agent_catalog']))
    receipt = dict(schema='simz1-random-selection-v2' if candidate_id is not None else 'simz1-random-selection-v1',**identity,
        entropy_source='secrets.token_hex',entropy_bytes=32,
        **draw,selected_non_public_vehicles=n,rejection_attempts=draw['counter'],
        physical_sources=sources,physical_sources_sha256=_sha_bytes(_json_bytes(sources)),
        base_scenario_identity=base_identity(trial_specification()),
        composition=dict(composition['family_counts'],public_transport=269),
        composition_rounding=composition['rounding'],demand_seed=20261023,service_date='2026-10-23',iterations=1)
    # No receipt is published if inputs changed while it was assembled.
    _validate_receipt(receipt,policy_sha)
    doc = _random_document(receipt,policy,policy_sha)
    _exclusive_write(folder/'selection.json',_json_bytes(receipt))
    _exclusive_write(folder/'selection.sha256',(doc['selection_sha256']+'\n').encode('ascii'))
    _exclusive_write(folder/'experiment.json',_json_bytes(doc))
    return experiment(folder/'experiment.json',RANDOM_SCENARIO)


def verify_selection_identity(recorded, expected):
    """Full experiment identity, allowing only copied input path and CLI quotas."""
    diagnostic = expected.get('schema') in (DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA)
    strict = expected.get('schema') in ('simz1-final-experiments-v3',RANDOM_SCHEMA,DIAGNOSTIC_SCHEMA,ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA)
    ignored = {'specification_path'} if diagnostic else {'specification_path','composition'}
    if not isinstance(recorded,dict): raise ValueError('Missing experiment selection')
    left = {k:v for k,v in recorded.items() if k not in ignored}
    right = {k:v for k,v in expected.items() if k not in ignored}
    differs = _json_bytes(left) != _json_bytes(right) if strict else left != right
    if differs:
        raise ValueError('Experiment selection identity differs')
    if recorded.get('composition') is not None:
        composition=expected.get('composition',expected.get('selection',{}).get('composition'))
        if expected.get('schema') == 'simz1-final-experiments-v3':
            # v3 stores quotas in the CLI transport only. Rebuild those quotas
            # from the authorized selection/catalog, never from received values.
            composition=require_scale(expected['total_non_public_vehicles'],expected['demand_seed'],
                expected['iterations'],expected['specification_path'],expected['scenario'])
        if (_json_bytes(recorded['composition']) != _json_bytes(composition) if strict else
                recorded['composition'] != composition):
            raise ValueError('Experiment composition differs')


def launch_postprocessing_policy(selected, requested=None):
    """Resolve an explicit launch policy without rewriting experiment identity.

    The input selection has already passed experiment(). Fixed v5 carries its
    native-only policy; supported v3 load selectors and v4 require an explicit
    opt-in to defer replay. Omitted values preserve their historical behavior.
    """
    automatic='automatic_replay_v1'; native='native_diagnostic_v1'
    if requested not in (None,automatic,native):
        raise ValueError('Unsupported launch postprocessing policy')
    schema=selected.get('schema'); scenario=selected.get('scenario')
    if schema in (DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        allowed = (DIAGNOSTIC_SCENARIO,) if schema == DIAGNOSTIC_SCHEMA else (('run1000','run10000','run55000') if schema == TRANSIT_SCHEMA else ('run1000','run10000','run55000','run110000'))
        if scenario not in allowed or selected.get('postprocessing',{}).get('policy') != native:
            raise ValueError('Diagnostic selection lacks its intrinsic native postprocessing policy')
        if requested not in (None,native):
            raise ValueError('Diagnostic experiment requires native_diagnostic_v1')
        return native
    if schema not in (EXPERIMENT_SCHEMA,'simz1-final-experiments-v2',
                      'simz1-final-experiments-v3',RANDOM_SCHEMA):
        raise ValueError('Unknown experiment postprocessing scope')
    if requested == native and not ((schema == 'simz1-final-experiments-v3' and scenario in ('half','max-test')) or
                                   (schema == RANDOM_SCHEMA and scenario == RANDOM_SCENARIO)):
        raise ValueError('Native diagnostic opt-in is not authorized for this selector')
    return requested or automatic


def verify_launch_request(request, expected):
    verify_selection_identity(request.get('experiment'),expected)
    if expected.get('schema') in ('simz1-final-experiments-v3',RANDOM_SCHEMA,DIAGNOSTIC_SCHEMA,ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA) and any(type(request.get(k)) is not int for k in (
            'minimum_non_public_vehicles','maximum_non_public_vehicles','iterations','demand_seed',
            'matsim_seed','first_iteration','last_iteration','public_vehicles','transmetro_vehicles','tubus_vehicles')):
        raise ValueError('Launch counts, seeds and iteration indices must be integers')
    if (request.get('minimum_non_public_vehicles') != expected['total_non_public_vehicles'] or
            request.get('maximum_non_public_vehicles') != expected['total_non_public_vehicles'] or
            request.get('iterations') != expected['iterations'] or request.get('demand_seed') != expected['demand_seed'] or
            request.get('matsim_seed') != expected['demand_seed'] or
            request.get('first_iteration') != 0 or request.get('last_iteration') != expected['iterations']-1 or
            request.get('service_date') != expected['service_date'] or
            request.get('public_vehicles') != 269 or request.get('transmetro_vehicles') != 176 or request.get('tubus_vehicles') != 93 or
            request.get('od_mode') != 'balanced-gateway-v1'):
        raise ValueError('Launch request differs from selected population or base')


def validate_manifest_selection(manifest, expected):
    recorded = manifest.get('experiment')
    if not isinstance(recorded,dict): raise ValueError('Missing experiment selection')
    selected = dict(recorded)
    population_sha = selected.pop('initial_population_sha256',None)
    population_basis = selected.pop('population_identity_basis',None)
    verify_selection_identity(selected,expected)
    if expected.get('schema') in (ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        policy = expected['origin_admission_policy']
        record = manifest.get('origin_admission_policy', {})
        if (any(record.get(k) != v for k, v in policy.items()) or
                record.get('effective_policy') != policy['version'] or
                record.get('source') != 'explicit versioned experiment' or
                record.get('artifact') != dict(path='inputs/origin-admission-policy.json', sha256=policy['policy_sha256'])):
            raise ValueError('Native origin admission policy provenance differs')
    if expected.get('schema') in (FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        policy = expected['freight_timing_policy']
        if (manifest.get('freight_completion_policy') != policy['version'] or
                manifest.get('inputs',{}).get('input:freight-completion-policy.json') !=
                dict(path='inputs/freight-completion-policy.json', sha256=policy['policy_sha256'])):
            raise ValueError('Native freight timing policy provenance differs')
    # The generator adds these two native fields after the draw is pinned.
    # They are legitimate derivations, but cannot be ignored: bind the exact
    # initial plans artifact while keeping request/selection identity strict.
    plans = manifest.get('inputs',{}).get('plans',{})
    if (not isinstance(population_sha,str) or not re.fullmatch('[0-9a-f]{64}',population_sha) or
            plans.get('path') != 'plans.xml' or plans.get('sha256') != population_sha or
            population_basis != 'initial plans bytes; iteration count does not enter demand RNG or population serialization'):
        raise ValueError('Experiment initial population identity differs from pinned plans')
    n = expected['total_non_public_vehicles']
    iterations = manifest.get('iterations',{})
    expected_iterations = dict(first=0,last=expected['iterations']-1,requested=expected['iterations'])
    completed = iterations.get('completed',[])
    # Preparation has an empty completion list; subsequent native iterations
    # must form the same ordered prefix of the authorized selection. This does
    # not promote the manifest to completed/valid or authorize new iterations.
    if (any(type(iterations.get(k)) is not int for k in expected_iterations) or
            not isinstance(completed,list) or any(type(i) is not int for i in completed) or
            len(completed)>expected['iterations'] or completed!=list(range(len(completed)))):
        raise ValueError('Native manifest iteration range or completion prefix differs')
    if expected.get('schema') in (DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        numeric = [manifest.get('demand_seed'), manifest.get('matsim_seed'),
                   manifest.get('demand_composition',{}).get('total_non_public_vehicles'),
                   manifest.get('counts',{}).get('public_transport_vehicles_configured')]
        numeric.extend(iterations.get(k) for k in ('first','last','requested'))
        numeric.extend(iterations.get('completed',[]))
        numeric.extend(manifest.get('demand_composition',{}).get('family_counts',{}).values())
        if any(type(value) is not int for value in numeric):
            raise ValueError('Diagnostic native counts, seeds and iteration indices must be integers')
    if (manifest.get('demand_composition',{}).get('total_non_public_vehicles') != n or
            manifest.get('demand_seed') != expected['demand_seed'] or manifest.get('matsim_seed') != expected['demand_seed'] or
            any(iterations.get(k) != v for k,v in expected_iterations.items()) or
            manifest.get('spatial_demand',{}).get('mode') != 'balanced-gateway-v1'):
        raise ValueError('Native manifest differs from selected N, iteration, seeds or OD base')
    if expected.get('schema') in (RANDOM_SCHEMA, DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        composition = (expected['selection']['composition'] if expected['schema'] == RANDOM_SCHEMA
                       else expected['composition'])
        if (manifest.get('demand_composition',{}).get('family_counts') != {k:composition[k] for k in ('carro','moto','pesado')} or
                manifest.get('counts',{}).get('public_transport_vehicles_configured') != 269):
            raise ValueError('Native manifest composition or buses differ from selection')
        # The generator audits its prepared document before the executor adds
        # launch_id. That state proves only preparation, never native execution.
        # Every started/finished manifest must carry the consumed Run identity.
        if expected['schema'] == RANDOM_SCHEMA and (manifest.get('status') != 'prepared' or manifest.get('launch_id') is not None):
            validate_run_claim(expected,manifest.get('launch_id'))


def validate_run_claim(selected, launch_id):
    """A native manifest/monitor must belong to the one consumed Run identity."""
    if not isinstance(launch_id,str) or not re.fullmatch('[0-9a-f]{32}',launch_id):
        raise ValueError('Missing or invalid Run LaunchId for random selection')
    path = SELECTION_ROOT/selected['selection']['selection_id']/'run-claim.json'
    claim = json.loads(path.read_bytes())
    expected = dict(schema='simz1-random-run-claim-v1',
                    selection_id=selected['selection']['selection_id'],launch_id=launch_id,
                    selection_sha256=selected['selection_sha256'],
                    specification_sha256=selected['specification_sha256'],
                    source_fingerprint=selected['selection']['source_fingerprint'],
                    created_utc=claim.get('created_utc'))
    if path.is_symlink() or claim != expected:
        raise ValueError('Run claim differs from the selection, sources or LaunchId')
    try:
        instant = datetime.fromisoformat(claim['created_utc'])
        if instant.utcoffset() != timezone.utc.utcoffset(instant): raise ValueError()
    except (TypeError,ValueError):
        raise ValueError('Run claim time must be an explicit UTC timestamp') from None
    return claim


def claim_selection(selected, launch_id):
    """Consume one selection once, immediately before an eligible native launch."""
    if selected.get('schema') != RANDOM_SCHEMA: raise ValueError('Claim requires the random experiment')
    if not re.fullmatch('[0-9a-f]{32}',str(launch_id)): raise ValueError('Invalid Run LaunchId')
    current = experiment(selected['specification_path'],selected['scenario'])
    verify_selection_identity(selected,current)
    receipt = current['selection']
    claim = dict(schema='simz1-random-run-claim-v1',selection_id=receipt['selection_id'],launch_id=launch_id,
                 selection_sha256=current['selection_sha256'],specification_sha256=current['specification_sha256'],
                 source_fingerprint=receipt['source_fingerprint'],created_utc=datetime.now(timezone.utc).isoformat())
    _exclusive_write(SELECTION_ROOT/receipt['selection_id']/'run-claim.json',_json_bytes(claim))
    return claim


def base_identity(doc):
    """Same for every selector; revision fingerprint additionally binds dependencies."""
    inputs = {}
    for key, relative in doc['base_inputs'].items():
        path = PROJECT/relative
        if not path.is_file(): raise ValueError('Required experiment input absent: '+relative)
        inputs[key] = dict(path=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    payload = dict(inputs=inputs, demand_seed=doc['demand_seed'], service_date=doc['service_date'],
                   observation_policy=doc['observation_policy'], observation_end_seconds=doc['observation_end_seconds'],
                   native_qsim_end_seconds=doc['native_qsim_end_seconds'], public_vehicles=doc['public_vehicles'])
    if doc.get('schema') in (ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        origin_policy_for_selection(doc)
        payload['origin_admission_policy'] = doc['origin_admission_policy']
    if doc.get('schema') in (FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        policy = freight_policy_identity()
        if doc.get('freight_timing_policy') != policy or doc.get('freight_completion_policy') != policy['version']:
            raise ValueError('Selected freight timing policy differs')
        payload['freight_timing_policy'] = policy
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def require_base_inputs(selected, **actual):
    if not selected.get('base_inputs'): return  # Historical contracts retain their own validation.
    for key, value in actual.items():
        if key not in selected['base_inputs']: raise ValueError('Unknown experiment input: '+key)
        expected = (PROJECT/selected['base_inputs'][key]).resolve(strict=True)
        if value is None or Path(value).resolve(strict=True) != expected:
            raise ValueError('Experiment base input differs: '+key)


def require_scale(total, seed=20261023, iterations=1, experiment_spec=None, experiment_scenario=None):
    selected=experiment(experiment_spec,experiment_scenario) if experiment_spec is not None else None
    if selected is None and experiment_scenario is not None:raise ValueError('Scenario requires an experiment specification')
    authorized=(total in BALANCED_TOTALS and iterations==1) if selected is None else (total==selected['total_non_public_vehicles'] and iterations==selected['iterations'])
    if type(total) is not int or type(iterations) is not int or not authorized or seed != 20261023:
        raise ValueError('Balanced scale requires exact authorized N, seed=20261023 and iteration count; new scenarios require their specification')
    if selected is not None and selected.get('schema') in (DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA) and type(seed) is not int:
        raise ValueError('Diagnostic demand seed must be an integer')
    from simz1_demand_composition import split
    from simz1_agent_types import load_catalog
    catalog=load_catalog(Path(__file__).resolve().parents[1]/'scenarios/zona1/agent-types-balanced-v1.json')
    composition = dict(split(total,catalog)['family_counts'],public_transport=269)
    if selected is not None and selected.get('schema') in (DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA) and composition != selected['composition']:
        raise ValueError('Diagnostic composition differs from the authorized fixed quotas')
    return composition


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path);p.add_argument('--scenario')
    p.add_argument('--draw',action='store_true',help='Create one new immutable random selection; never launch a simulation')
    p.add_argument('--candidate-id',help='Explicit UUIDv4 hex candidate for one immutable draw; only with --draw')
    p.add_argument('--launch-request',type=Path);p.add_argument('--run-manifest',type=Path)
    p.add_argument('--claim-launch-id',help='Consume an already validated selection for one identified Run')
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.draw:
        if a.spec or a.scenario or a.launch_request or a.run_manifest or a.claim_launch_id or a.output:
            p.error('--draw creates its own immutable artifacts and accepts no spec, verification, claim or output override')
        row=create_random_selection(a.candidate_id)
    else:
        if a.candidate_id is not None:p.error('--candidate-id requires --draw; it cannot replace an existing selection')
        if not a.spec or not a.scenario:p.error('--spec and --scenario are required without --draw')
        row=experiment(a.spec,a.scenario)
    row['composition']=require_scale(row['total_non_public_vehicles'],row['demand_seed'],row['iterations'],row['specification_path'],row['scenario'])
    if a.launch_request:verify_launch_request(json.loads(a.launch_request.read_text(encoding='utf-8-sig')),row)
    if a.run_manifest:validate_manifest_selection(json.loads(a.run_manifest.read_text(encoding='utf-8-sig')),row)
    if a.claim_launch_id:claim_selection(row,a.claim_launch_id)
    value=json.dumps(row,indent=2)+'\n'
    if a.output:a.output.write_text(value,encoding='utf-8')
    else:print(value,end='')


if __name__=='__main__':main()
