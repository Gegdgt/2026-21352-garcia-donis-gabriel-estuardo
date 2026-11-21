"""Executable design for SimZ1 synthetic incident detection, fixtures ONLY.

No MATSim integration, network mutation, renderer input or global random state.
The native paired observer and a reviewed real conflict registry do not exist
yet. This reference deliberately refuses production input instead of inferring
an encounter from old decision events or a WebGL overlap.
"""
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

MODEL = 'simz1-synthetic-incident-design-v1'
DAY_US = 86_400_000_000
HASH_FIELDS = ('network', 'lanes', 'restrictions', 'osm', 'vehicle_types')
FAMILIES = {'car', 'motorcycle', 'truck', 'bus'}


def canonical(value):
    """UTF-8 JSON, sorted object keys, no whitespace/NaN; arrays retain order."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def text(value):
    return isinstance(value, str) and bool(value.strip())


def known_level(value):
    if not text(value):
        return False
    try:
        return math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False


def sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def audit_value(value):
    """Retain invalid evidence in a JSON-safe diagnostic, never repair an input."""
    if isinstance(value, dict):
        return {str(k): audit_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [audit_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {'invalid_number': str(value)}
    if value is None or type(value) in (str, int, float, bool):
        return value
    return {'invalid_type': type(value).__name__}


@dataclass(frozen=True)
class IncidentDesignConfig:
    enabled: bool = False
    incident_seed: int | None = None
    probability_per_opportunity: float = .00001
    daily_cap: int = 5
    active_duration_us: int = 900_000_000

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('enabled must be boolean')
        if self.incident_seed is not None and (type(self.incident_seed) is not int or
                not -(2**63) <= self.incident_seed < 2**63):
            raise ValueError('incident_seed must be an independent signed 64-bit integer')
        if self.enabled and self.incident_seed is None:
            raise ValueError('enabled detection requires an explicit independent incident_seed')
        p = self.probability_per_opportunity
        if not finite_number(p) or not 0 <= p <= 1:
            raise ValueError('synthetic probability must be finite and in [0,1]')
        if not integer(self.daily_cap) or self.daily_cap > 5:
            raise ValueError('daily_cap must be an integer in [0,5]; there is no minimum quota')
        if not integer(self.active_duration_us, 1):
            raise ValueError('active_duration_us must be a positive integer')

    def manifest(self):
        result = asdict(self)
        # A string preserves all 64 seed bits in JSON/JavaScript consumers.
        result['incident_seed'] = None if self.incident_seed is None else str(self.incident_seed)
        return dict(model=MODEL, **result, seed_source='explicit_independent_not_MatsimRandom',
                    probability_basis='synthetic_per_unique_eligible_opportunity_not_empirical',
                    active_duration_meaning='annotation_exclusion_only_no_physical_effect',
                    collision_detection_available=False, physics_effect='none',
                    rng='SHA256-canonical-JSON-first-64-bits-big-endian-v1')


def draw(seed, replication_key, iteration, registry_hash, opportunity_key):
    """Order-independent random bits; no run UUID, frame clock or global PRNG."""
    material = [MODEL, 'incident-draw', str(seed), replication_key, iteration, registry_hash, opportunity_key]
    return int.from_bytes(hashlib.sha256(canonical(material)).digest()[:8], 'big')


def visual_input(value):
    if isinstance(value, dict):
        return any(str(k).lower().startswith(('visual_', 'webgl', 'hitbox', 'screen_', 'pixel_')) or
                   visual_input(v) for k, v in value.items())
    if isinstance(value, list):
        return any(visual_input(v) for v in value)
    return False


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _proper_crossing(a, b):
    try:
        if any(len(p) != 2 or any(not finite_number(v) for v in p)
               for p in [*a, *b]) or len(a) != 2 or len(b) != 2:
            return False
        c = [_cross(*a, b[0]), _cross(*a, b[1]), _cross(*b, a[0]), _cross(*b, a[1])]
        return (all(finite_number(v) and abs(v) > 1e-6 for v in c) and
                (c[0] < 0) != (c[1] < 0) and (c[2] < 0) != (c[3] < 0))
    except (TypeError, IndexError):
        return False


def validate_registry(registry):
    if not isinstance(registry, dict):
        raise ValueError('Registry must be an object')
    if registry.get('schema') != 'simz1-conflict-registry-design-v1' or registry.get('scope') != 'fixture_only':
        raise ValueError('Production integration pending: only explicitly synthetic fixture registries are accepted')
    if visual_input(registry) or registry.get('geometry_source') != 'native_network_fixture':
        raise ValueError('Registry cannot be based on renderer geometry')
    hashes = registry.get('artifact_sha256', {})
    if not isinstance(hashes, dict) or set(hashes) != set(HASH_FIELDS) or not all(sha(hashes[k]) for k in HASH_FIELDS):
        raise ValueError('Registry requires network, lanes, restrictions, OSM and VehicleType fingerprints')
    movements, zones = registry.get('movements', {}), registry.get('zones', {})
    if not isinstance(movements, dict) or not isinstance(zones, dict):
        raise ValueError('Movements and zones must be objects')
    try:
        canonical(registry)
    except (TypeError, ValueError):
        raise ValueError('Registry must be finite JSON') from None
    for ident, movement in movements.items():
        if (not isinstance(movement, dict) or not text(ident) or any(not text(movement.get(k)) for k in
                ('node_id', 'in_link', 'out_link', 'lane_id', 'receiving_lane_id', 'level', 'evidence_ref')) or
                movement.get('turn_verified') is not True):
            raise ValueError('Unknown, forbidden or unverified movement')
        families = movement.get('families')
        if not isinstance(families, list) or not families or any(not text(f) or f not in FAMILIES for f in families):
            raise ValueError('Movement requires verified vehicle family permissions')
        if not known_level(movement['level']):
            raise ValueError('Unknown grade cannot be turned into a same-level conflict')
    for ident, zone in zones.items():
        if not isinstance(zone, dict):
            raise ValueError('Conflict zone must be an object')
        ids = zone.get('movement_ids', [])
        if (not text(ident) or not isinstance(ids, list) or len(ids) != 2 or any(not text(i) for i in ids) or
                len(set(ids)) != 2 or any(i not in movements for i in ids)):
            raise ValueError('Conflict zone requires two distinct known movements')
        a, b = [movements[i] for i in ids]
        if (zone.get('review_status') != 'verified_fixture' or zone.get('restrictions_resolved') is not True or
                not text(zone.get('place_id')) or not text(zone.get('evidence_ref')) or
                a['node_id'] != b['node_id'] or zone.get('node_id') != a['node_id'] or
                a['level'] != b['level'] or a['in_link'] == b['in_link']):
            raise ValueError('Ambiguous place, grade, restrictions or same-approach pair is not an eligible conflict')
        kind = zone.get('risk_type')
        if kind == 'merge_demand':
            valid = zone.get('proof') == 'shared_receiving_lane' and a['out_link'] == b['out_link'] and a['receiving_lane_id'] == b['receiving_lane_id']
        elif kind == 'crossing_demand':
            valid = (zone.get('proof') == 'reviewed_same_level_crossing' and a['out_link'] != b['out_link'] and
                     _proper_crossing(a.get('chord_xy'), b.get('chord_xy')))
        else:
            valid = False
        if not valid:
            raise ValueError('Positive crossing/merge evidence is required; conservative conflicts are insufficient')


def _validate_observation(row, registry, start_us, end_us, complete_until_us):
    if not isinstance(row, dict):
        return 'malformed_observation'
    if visual_input(row):
        return 'visual_evidence_forbidden'
    try:
        canonical(row)
    except (TypeError, ValueError):
        return 'non_json_or_nonfinite_input'
    t = row.get('time_us')
    if not integer(t) or not start_us <= t < end_us or t > complete_until_us:
        return 'invalid_or_unclosed_chronology'
    if row.get('schema') != 'simz1-native-pair-design-v1' or row.get('source') != 'node_owned_paired_snapshot' or row.get('step_complete') is not True:
        return 'paired_native_evidence_missing'
    if row.get('artifact_sha256') != registry['artifact_sha256']:
        return 'artifact_identity_mismatch'
    if not text(row.get('zone_id')):
        return 'unknown_conflict_or_node'
    zone = registry['zones'].get(row['zone_id'])
    if zone is None or row.get('node_id') != zone['node_id']:
        return 'unknown_conflict_or_node'
    people = row.get('participants')
    if not isinstance(people, list) or len(people) != 2 or any(not isinstance(p, dict) for p in people):
        return 'two_native_participants_required'
    if any(p.get('decision') == 'FORCE' for p in people):
        return 'forced_transition_excluded'
    if any(p.get('decision') == 'ABORT' for p in people):
        return 'aborted_transition_excluded'
    if any(not text(p.get('movement_id')) for p in people) or set(p['movement_id'] for p in people) != set(zone['movement_ids']):
        return 'movement_pair_mismatch'
    if any(not text(p.get('vehicle_id')) for p in people):
        return 'vehicle_or_visit_identity_missing'
    if len(set(p['vehicle_id'] for p in people)) != 2:
        return 'same_vehicle_pair'
    for p in people:
        if any(not text(p.get(k)) for k in ('vehicle_id', 'trip_id', 'type_id', 'evidence_ref')) or not integer(p.get('visit_index')):
            return 'vehicle_or_visit_identity_missing'
        if p.get('person_id') is not None and not text(p['person_id']):
            return 'person_identity_invalid'
        if p.get('route_known') is not True or not text(p.get('family')) or p['family'] not in FAMILIES:
            return 'route_or_vehicle_family_unknown'
        movement = registry['movements'][p['movement_id']]
        if (p.get('link_id') != movement['in_link'] or p.get('lane_id') != movement['lane_id'] or
                p['family'] not in movement['families']):
            return 'lane_link_or_family_permission_mismatch'
        if not integer(p.get('entered_queue_us')) or p['entered_queue_us'] > t:
            return 'queue_entry_after_observation'
        dimensions = p.get('dimensions', {})
        if (not isinstance(dimensions, dict) or dimensions.get('nature') != 'configured' or
                not text(dimensions.get('source')) or dimensions.get('artifact_sha256') != registry['artifact_sha256']['vehicle_types'] or
                any(not finite_number(dimensions.get(k)) or dimensions[k] <= 0
                    for k in ('length_m', 'width_m'))):
            return 'configured_dimensions_missing_no_car_fallback'
        if p.get('decision') == 'ADMITTED':
            if p.get('reason') != 'native_admitted' or p.get('receiver_accepted') is not True:
                return 'admission_receipt_missing'
        elif p.get('decision') == 'WAIT':
            if p.get('reason') not in ('movement_conflict', 'priority_conflict', 'signal_conflict'):
                return 'wait_without_traffic_conflict'
        else:
            return 'unknown_native_decision'
    if sorted(p['decision'] for p in people) != ['ADMITTED', 'WAIT']:
        return 'requires_one_admitted_and_one_conflicting_demand'
    return None


def opportunity_key(row, registry):
    # One encounter per place and pair of visits, irrespective of repeated WAIT,
    # lane retries, presentation, route changes or multiple zones at that place.
    visits = sorted([p['vehicle_id'], p['trip_id'], p['visit_index']] for p in row['participants'])
    return fingerprint([MODEL, 'encounter', registry['zones'][row['zone_id']]['place_id'], visits])


def evaluate(config, registry, observations, *, replication_key='fixture', iteration=0,
             start_us=0, end_us=DAY_US, complete_until_us=None):
    """Evaluate a COMPLETE finite fixture batch; never a live per-frame hook.

    Sort after the producer watermark, deduplicate encounter visits, draw once,
    then apply annotation exclusion and a daily ceiling. No minimum count.
    """
    result = dict(manifest=config.manifest(), opportunities=[], incidents=[], rejected=[],
                  forced_transitions=[], counts={}, physics_effect='none')
    if not config.enabled:
        result['counts'] = dict(enabled=False, observations_received=0, unique_eligible=0, trials=0, incidents=0)
        return result  # In particular, do not consume observations or load registry.
    if not text(replication_key) or not integer(iteration) or not integer(start_us) or not integer(end_us, start_us+1):
        raise ValueError('Invalid experiment identity or simulated horizon')
    if complete_until_us is None:
        raise ValueError('A completed producer watermark is required, not a partial node callback')
    if not integer(complete_until_us) or complete_until_us != end_us:
        raise ValueError('Complete fixture batch required: completed watermark must equal end_us')
    validate_registry(registry)
    registry_hash = fingerprint(registry)
    result['manifest'].update(registry_sha256=registry_hash, artifact_sha256=copy.deepcopy(registry['artifact_sha256']),
        replication_key=replication_key, iteration=iteration, start_us=start_us, end_us=end_us,
        complete_until_us=complete_until_us, scope='fixture_only')
    counts = Counter(observations_received=0, unique_eligible=0, duplicate_observations=0, trials=0,
                     draw_successes=0, active_suppressed=0, daily_cap_suppressed=0, incidents=0)
    candidates, blocked_encounters, evidence_by_encounter = [], set(), {}
    for original in observations:
        counts['observations_received'] += 1
        reason = _validate_observation(original, registry, start_us, end_us, complete_until_us)
        if reason:
            result['rejected'].append(dict(reason=reason, observation=audit_value(original)))
            if reason == 'forced_transition_excluded':
                result['forced_transitions'].append(copy.deepcopy(original))
            if reason in ('forced_transition_excluded', 'aborted_transition_excluded'):
                # Contradictory reports of the same visit/pair/instant must not
                # permit a second apparently valid receipt to create an event.
                people = original['participants']
                if all(text(p.get('vehicle_id')) and text(p.get('trip_id')) and integer(p.get('visit_index')) for p in people):
                    blocked_encounters.add(opportunity_key(original, registry))
            continue
        row = copy.deepcopy(original)
        row['participants'].sort(key=lambda p: (p['vehicle_id'], p['trip_id'], p['visit_index']))
        key = opportunity_key(row, registry)
        encounter = (row['time_us'], key)
        signature = fingerprint([{k: v for k, v in p.items() if k != 'evidence_ref'} for p in row['participants']])
        if encounter in evidence_by_encounter and evidence_by_encounter[encounter] != signature:
            blocked_encounters.add(key)
        evidence_by_encounter[encounter] = signature
        candidates.append((row['time_us'], row['node_id'], key, fingerprint(row), row))
    seen, active_vehicles, active_places, daily = set(), {}, {}, Counter()
    threshold = int(Decimal(str(config.probability_per_opportunity)) * (2**64))
    for t, node, key, _, row in sorted(candidates, key=lambda item: item[:4]):
        if key in blocked_encounters:
            result['rejected'].append(dict(reason='contradictory_native_evidence', observation=row))
            continue
        if key in seen:
            counts['duplicate_observations'] += 1
            continue
        seen.add(key)
        counts['unique_eligible'] += 1
        zone = registry['zones'][row['zone_id']]
        bits = draw(config.incident_seed, replication_key, iteration, registry_hash, key)
        counts['trials'] += 1
        trial = dict(opportunity_id=key, time_us=t, node_id=node, zone_id=row['zone_id'], place_id=zone['place_id'],
            participants=row['participants'], risk_type=zone['risk_type'], evidence_ref=zone['evidence_ref'],
            classification='verified_network_conflict_exposure_not_collision', draw_hex=f'{bits:016x}',
            threshold_decimal=str(threshold), selected_before_exclusions=bits < threshold, outcome='not_selected')
        result['opportunities'].append(trial)
        if bits >= threshold:
            continue
        counts['draw_successes'] += 1
        vehicles = [p['vehicle_id'] for p in row['participants']]
        # [start,end): reservations survive midnight, expire exactly at end.
        if active_places.get(zone['place_id'], -1) > t or any(active_vehicles.get(v, -1) > t for v in vehicles):
            counts['active_suppressed'] += 1
            trial['outcome'] = 'active_vehicle_or_place'
            continue
        day = t // DAY_US
        if daily[day] >= config.daily_cap:
            counts['daily_cap_suppressed'] += 1
            trial['outcome'] = 'daily_cap'
            continue
        until = t + config.active_duration_us
        for v in vehicles:
            active_vehicles[v] = until
        active_places[zone['place_id']] = until
        daily[day] += 1
        counts['incidents'] += 1
        trial['outcome'] = 'synthetic_incident'
        ident = 'synth-' + fingerprint([MODEL, 'incident', str(config.incident_seed), replication_key, iteration, registry_hash, key])
        result['incidents'].append(dict(event_type='simz1SyntheticIncidentDesign', incident_id=ident,
            opportunity_id=key, time_us=t, simulated_day=day, node_id=node, zone_id=row['zone_id'], place_id=zone['place_id'],
            links=sorted(set(p['link_id'] for p in row['participants'])),
            lanes=[dict(link_id=p['link_id'], lane_id=p['lane_id']) for p in row['participants']],
            participants=copy.deepcopy(row['participants']), risk_type=zone['risk_type'],
            modeled_cause='synthetic_residual_risk_at_verified_conflict', classification='stochastic_synthetic_accident',
            collision_detected=False, collision_observation='not_available_in_qsim_queue', observed_violation=False, physics_effect='none',
            probability_per_opportunity=config.probability_per_opportunity, draw_hex=trial['draw_hex'],
            incident_seed=str(config.incident_seed), evidence=dict(registry_sha256=registry_hash,
                conflict=zone['evidence_ref'], paired_observer=row['source'], artifact_sha256=copy.deepcopy(registry['artifact_sha256'])),
            scheduled_annotation_end_us=until, annotation_status_at_horizon='expired' if until <= end_us else 'censored'))
    # Audit output, too, is independent of parallel producer delivery order.
    result['rejected'].sort(key=lambda value: canonical(value))
    result['forced_transitions'].sort(key=canonical)
    result['counts'] = dict(counts, enabled=True, rejected=len(result['rejected']),
        rejection_reasons=dict(sorted(Counter(r['reason'] for r in result['rejected']).items())),
        incidents_by_day={str(k): v for k, v in sorted(daily.items())},
        expected_draw_successes_before_exclusions=counts['trials']*config.probability_per_opportunity,
        realized_per_opportunity=counts['incidents']/counts['trials'] if counts['trials'] else None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--output-new', type=Path)
    args = parser.parse_args()
    request = json.loads(args.fixture.read_text(encoding='utf-8'))
    report = evaluate(IncidentDesignConfig(**request['config']), request.get('registry'), request.get('observations'),
                      **request['experiment'])
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output_new:
        with args.output_new.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(encoded)
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
