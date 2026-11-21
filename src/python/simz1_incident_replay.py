"""Read the lane-incident wire contract without enabling a native adapter.

Production integration is unavailable. Explicit fixture parsing is useful for
cross-language checks; neither the exporter nor the viewer enables that option.
Legacy perturbations, design annotations and FORCE are never colored by this
contract. Unknown or inconsistent evidence remains in diagnostics.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import math


EVENT_SCHEMA = 'simz1-lane-incident-v1'
REPLAY_SCHEMA = 'simz1-lane-incident-replay-v1'
PREFIX = 'simz1LaneIncident'
EVENT_STATES = {PREFIX + 'Start': 'active', PREFIX + 'Resolved': 'resolved', PREFIX + 'Censored': 'censored'}
DURATION_SECONDS = 1800
MAX_SAFE_US = 9_007_199_254_740_991


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _audit(value):
    if isinstance(value, dict):
        return {str(k): _audit(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_audit(v) for v in value]
    if type(value) is float and not math.isfinite(value):
        return {'invalid_number': str(value)}
    if value is None or type(value) in (str, int, float, bool):
        return value
    return {'invalid_type': type(value).__name__}


def _seconds(value):
    if type(value) not in (str, int, float):
        raise ValueError('invalid_timestamp')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal(MAX_SAFE_US) / 1_000_000:
            raise ValueError('invalid_timestamp')
        if number != number.quantize(Decimal('0.000001')):
            raise ValueError('invalid_timestamp')
        return number
    except (InvalidOperation, OverflowError):
        raise ValueError('invalid_timestamp') from None


class NativeIncidentAdapterUnavailable(ValueError):
    """The original XML remains authoritative; expose the rejected raw record."""
    def __init__(self, attrs):
        self.diagnostic = {'reason': 'adapter_not_installed', 'event': _audit(attrs)}
        super().__init__('adapter_not_installed: simz1LaneIncident events cannot be exported '
                         'without a native adapter; original event data is preserved')


def reject_uninstalled_native_incident(attrs):
    """Export/recovery guard; deliberately has no acceptsNative/fixture bypass."""
    kind = attrs.get('type')
    if isinstance(kind, str) and kind.startswith(PREFIX):
        raise NativeIncidentAdapterUnavailable(dict(attrs))


class LaneIncidentReplay:
    """Complete offline batch, not a live adapter or a guarantee of native physics.

    Lifecycle, contradiction and exclusion validation inspect the entire batch.
    Do not concatenate independently parsed partial batches as one iteration.
    Only explicit test fixtures can be decoded.
    """
    def __init__(self, run_id, iteration, horizon_seconds, *, allow_fixture=False):
        if not _text(run_id) or type(iteration) is not int or iteration < 0 or type(allow_fixture) is not bool:
            raise ValueError('invalid_replay_identity_or_fixture_option')
        self.horizon = _seconds(horizon_seconds)
        if self.horizon <= 0:
            raise ValueError('invalid_horizon')
        self.run_id, self.iteration, self.allow_fixture = run_id, iteration, allow_fixture
        self._starts, self._terminals, self._invalid = {}, {}, set()
        self._seen, self._diagnostics, self._counts = {}, [], Counter()
        self._previous = Decimal(-1)

    def _reject(self, reason, attrs, *, invalidate=True):
        self._diagnostics.append(dict(reason=reason, event_index=self._counts['received'], event=_audit(attrs)))
        self._counts['rejected'] += 1
        if invalidate and isinstance(attrs, dict) and _text(attrs.get('incidentId')):
            self._invalid.add(attrs['incidentId'])

    def consume(self, attrs):
        """Return whether this is incident-related; unrelated traffic is untouched."""
        if not isinstance(attrs, dict):
            self._counts['received'] += 1
            self._reject('malformed_event', attrs)
            return True
        kind = attrs.get('type')
        if kind in ('zona1IncidentStart', 'zona1IncidentRecovered'):
            self._counts['received'] += 1
            self._reject('legacy_incident_excluded', attrs, invalidate=False)
            return True
        if (isinstance(kind, str) and 'Incident' in kind and 'Design' in kind):
            self._counts['received'] += 1
            self._reject('design_annotation_excluded', attrs, invalidate=False)
            return True
        lane_incident = isinstance(kind, str) and kind.startswith(PREFIX)
        if attrs.get('decision') == 'FORCE' and not lane_incident:
            self._counts['received'] += 1
            self._reject('forced_transition_excluded', attrs, invalidate=False)
            return True
        if not lane_incident:
            return False
        self._counts['received'] += 1
        try:
            json.dumps(attrs, allow_nan=False)
        except (TypeError, ValueError):
            self._reject('non_json_or_nonfinite_input', attrs)
            return True
        # No externally supplied flag can certify a missing native implementation.
        if attrs.get('scope') != 'fixture_only':
            self._reject('adapter_not_installed', attrs)
            return True
        if not self.allow_fixture:
            self._reject('fixture_opt_in_required', attrs)
            return True
        if kind not in EVENT_STATES or attrs.get('schema') != EVENT_SCHEMA:
            self._reject('unknown_incident_type_or_schema', attrs)
            return True
        if attrs.get('decision') == 'FORCE':
            self._reject('forced_transition_excluded', attrs)
            return True
        try:
            claim = self._claim(attrs)
        except ValueError as error:
            self._reject(str(error), attrs)
            return True
        ident, stamp, state = claim['incident_id'], claim['event_time'], claim['state']
        if stamp < self._previous:
            self._reject('non_monotonic_incident_chronology', attrs)
            return True
        self._previous = stamp
        signature = {key: value for key, value in claim.items() if key != 'raw'}
        event_key = (ident, state)
        if event_key in self._seen:
            if self._seen[event_key] == signature:
                self._counts['duplicate_events'] += 1
            else:
                self._reject('contradictory_duplicate_event', attrs)
            return True
        self._seen[event_key] = signature
        if state == 'active':
            if ident in self._terminals:
                self._reject('start_after_terminal', attrs)
            else:
                self._starts[ident] = claim
        elif ident not in self._starts:
            self._reject('terminal_without_start', attrs)
        elif ident in self._terminals:
            self._reject('contradictory_terminal_state', attrs)
        else:
            start = self._starts[ident]
            stable = ('opportunity_id', 'link_id', 'lane', 'participants', 'start', 'scheduled_end', 'evidence_ref')
            if any(start[key] != claim[key] for key in stable):
                self._reject('terminal_identity_or_participants_mismatch', attrs)
            else:
                self._terminals[ident] = claim
        return True

    def _claim(self, attrs):
        if (attrs.get('physicsEffect') != 'none' or
                attrs.get('intendedPhysicsEffect') != 'independent_lane_hold' or
                attrs.get('adapterEvidence') != 'fixture_gate_only_not_native' or
                attrs.get('adapterVersion') != 'uninstalled'):
            raise ValueError('fixture_adapter_provenance_mismatch')
        if attrs.get('runId') != self.run_id or str(attrs.get('iteration')) != str(self.iteration):
            raise ValueError('run_identity_mismatch')
        for field in ('incidentId', 'opportunityId', 'link', 'lane', 'evidenceRef',
                      'vehicle1', 'vehicle2', 'vehicleType1', 'vehicleType2'):
            if not _text(attrs.get(field)):
                raise ValueError('missing_exact_identity_or_lane')
        if attrs['vehicle1'] == attrs['vehicle2']:
            raise ValueError('two_distinct_vehicles_required')
        if any(isinstance(key, str) and key.startswith('vehicle') and key[7:].isdigit()
               and key not in ('vehicle1', 'vehicle2') for key in attrs):
            raise ValueError('exactly_two_participants_required')
        if any(attrs.get(key) == 'FORCE' for key in ('decision1', 'decision2')):
            raise ValueError('forced_transition_excluded')
        participants = []
        for suffix in ('1', '2'):
            person = attrs.get('person' + suffix)
            if person is not None and not _text(person):
                raise ValueError('invalid_optional_person')
            # The shared LaneKey is guaranteed by the Java wire constructor.
            # If a producer adds per-participant locations, they cannot disagree.
            if any(attrs.get(field + suffix, attrs[field]) != attrs[field] for field in ('link', 'lane')):
                raise ValueError('participants_not_on_exact_same_lane')
            participants.append(dict(vehicle_id=attrs['vehicle' + suffix], person_id=person,
                vehicle_type=attrs['vehicleType' + suffix], link_id=attrs['link'], lane=attrs['lane']))
        participants.sort(key=lambda value: value['vehicle_id'])
        stamp, start, end, duration = [_seconds(attrs.get(field)) for field in
                                       ('time', 'startTime', 'scheduledEndTime', 'durationSeconds')]
        if duration != DURATION_SECONDS or end - start != DURATION_SECONDS:
            raise ValueError('duration_must_be_exactly_1800_seconds')
        state = EVENT_STATES[attrs['type']]
        if attrs.get('state') != state:
            raise ValueError('event_type_state_mismatch')
        if start >= self.horizon or stamp > self.horizon or stamp < start:
            raise ValueError('event_outside_observed_horizon')
        if ((state == 'active' and stamp != start) or (state == 'resolved' and stamp != end) or
                (state == 'censored' and (stamp != self.horizon or stamp >= end))):
            raise ValueError('invalid_lifecycle_boundary')
        return dict(incident_id=attrs['incidentId'], opportunity_id=attrs['opportunityId'],
                    link_id=attrs['link'], lane=attrs['lane'], participants=participants,
                    start=start, scheduled_end=end, event_time=stamp, state=state,
                    evidence_ref=attrs['evidenceRef'], raw=deepcopy(attrs))

    def payload(self):
        """Unclosed/invalid records stay diagnostic; never fabricate a recovery."""
        records, diagnostics = [], deepcopy(self._diagnostics)
        for ident, start in sorted(self._starts.items(), key=lambda item: (item[1]['start'], item[0])):
            if ident in self._invalid:
                continue
            terminal = self._terminals.get(ident)
            if terminal is None:
                diagnostics.append(dict(reason='missing_terminal_event', event=start['raw']))
                continue
            state = terminal['state']
            records.append(dict(incident_id=ident, opportunity_id=start['opportunity_id'],
                link_id=start['link_id'], lane=start['lane'], vehicles=[p['vehicle_id'] for p in start['participants']],
                participants=deepcopy(start['participants']), start_seconds=float(start['start']),
                scheduled_end_seconds=float(start['scheduled_end']), duration_seconds=DURATION_SECONDS,
                end_seconds=float(terminal['event_time']) if state == 'resolved' else None,
                censored_seconds=float(terminal['event_time']) if state == 'censored' else None,
                status=state, physics_effect='none', intended_physics_effect='independent_lane_hold',
                evidence_ref=start['evidence_ref'], provenance=dict(scope='fixture_only', adapter_version='uninstalled',
                    adapter_evidence='fixture_gate_only_not_native', start_event=deepcopy(start['raw']),
                    terminal_event=deepcopy(terminal['raw']))))
        invalid_records = set()
        for index, a in enumerate(records):
            for b in records[index+1:]:
                reason = None
                if a['opportunity_id'] == b['opportunity_id']:
                    reason = 'repeated_opportunity_across_incident_ids'
                else:
                    a_id, b_id = a['incident_id'], b['incident_id']
                    overlap = (max(self._starts[a_id]['start'], self._starts[b_id]['start']) <
                               min(self._terminals[a_id]['event_time'], self._terminals[b_id]['event_time']))
                    if overlap and (a['link_id'], a['lane']) == (b['link_id'], b['lane']):
                        reason = 'overlapping_incidents_on_exact_lane'
                    elif overlap and set(a['vehicles']) & set(b['vehicles']):
                        reason = 'overlapping_incidents_for_vehicle'
                if reason:
                    invalid_records.update((a['incident_id'], b['incident_id']))
                    diagnostics.append(dict(reason=reason, incident_ids=[a['incident_id'], b['incident_id']],
                        events=[a['provenance']['start_event'], b['provenance']['start_event']]))
        records = [record for record in records if record['incident_id'] not in invalid_records]
        return dict(schema=REPLAY_SCHEMA, scope='fixture_only', adapter_installed=False,
                    adapter_version='uninstalled', adapter_evidence='fixture_gate_only_not_native',
                    identity=dict(run_id=self.run_id, iteration=self.iteration), horizon_seconds=float(self.horizon),
                    records=records, diagnostics=diagnostics,
                    counts=dict(self._counts, records=len(records), diagnostics=len(diagnostics),
                                reasons=dict(Counter(item['reason'] for item in diagnostics))))


def parse_incident_events(events, *, run_id, iteration, horizon_seconds, allow_fixture=False):
    replay = LaneIncidentReplay(run_id, iteration, horizon_seconds, allow_fixture=allow_fixture)
    for attrs in events:
        replay.consume(attrs)
    return replay.payload()
