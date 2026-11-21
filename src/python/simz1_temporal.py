"""Synthetic SimZ1 departure assumptions, not measured or calibrated demand."""
import argparse
from bisect import bisect
from itertools import accumulate
import math
import random
import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DAY = 86400
POLICY_SCHEMA = 'simz1-weekday-continuous-v1'
POLICY_SCENARIO_VERSION = 'simz1-weekday-continuous-v1-synthetic-20261028'
COHORT_WINDOWS = {'main': 'study', 'warmup_context': 'warmup', 'post_context': 'post_demand'}
# Relative hourly intensity, 00..23. Normalize rather than imply observed counts.
DEFAULT_WEIGHTS = (1, .7, .5, .5, .8, 2, 6, 9, 8, 5, 4, 5,
                   6, 5, 4, 4, 6, 9, 8, 4, 3, 2, 1.5, 1)


def nonnegative_integer(value):
    try:
        if isinstance(value, bool) or str(int(value)) != str(value) or int(value) < 0:
            raise ValueError()
        return int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('Se requiere un entero no negativo') from None


def temporal_spec(profile=None, weights=None, trips=1, drain=None, mode='montecarlo'):
    if type(trips) is not int or trips < 1:
        raise ValueError('--trips-per-person debe ser un entero positivo')
    if mode == 'debug':
        if profile is not None or weights is not None or trips != 1 or drain is not None:
            raise ValueError('debug conserva su horario fijo; opciones temporales solo para historical/montecarlo')
        return None
    profile = profile or 'full-day'
    if profile not in ('full-day', 'peaks'):
        raise ValueError('--temporal-profile debe ser full-day o peaks')
    if profile == 'peaks' and (weights is not None or trips != 1):
        raise ValueError('peaks reproduce un viaje por persona; pesos horarios/viajes repetidos requieren full-day')
    if drain is None:
        # A normal run is one calendar day. Extra drain is an explicit experiment.
        drain = 0
    if type(drain) is not int or drain < 0:
        raise ValueError('--drain-seconds debe ser un entero no negativo')
    try:
        raw = DEFAULT_WEIGHTS if weights is None else (weights.split(',') if isinstance(weights, str) else weights)
        raw = [float(v) for v in raw]
        total = math.fsum(raw)
        if len(raw) != 24 or any(not math.isfinite(v) or v < 0 for v in raw) or not math.isfinite(total) or total <= 0:
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise ValueError('--hourly-weights requiere 24 pesos finitos no negativos y suma positiva') from None
    return dict(profile=profile, persons_are_N=True, trips_per_person=trips,
                hourly_weights=raw if profile == 'full-day' else None,
                hourly_probabilities=[w/total for w in raw] if profile == 'full-day' else None,
                weight_source='synthetic-default-v1' if weights is None else 'explicit-synthetic-assumption',
                demand_window=dict(start_seconds=0, end_seconds=DAY, end_exclusive=True),
                departure_intervals=[[0, DAY]] if profile == 'full-day' else [[21600,30600],[61200,70200]],
                simulation_window=dict(start_seconds=0 if profile == 'full-day' else 19800, end_seconds=DAY+drain),
                drain_seconds=drain,
                scheduling='Sorted planned departures; later trips may depart late if previous travel has not ended',
                rng='SimZ1-temporal-v1 independent seeded stream; peaks retains snapshot-v1 time draws')


class DepartureSampler:
    def __init__(self, seed, probabilities):
        self.rng = random.Random(f'SimZ1-temporal-v1:{seed}')
        self.cumulative = list(accumulate(probabilities))

    def sample(self, count=1):
        values = set()
        while len(values) < count:
            hour = bisect(self.cumulative, self.rng.random()*self.cumulative[-1])
            # Uniform seconds plus subsecond jitter; no mass at hourly boundaries.
            second = self.rng.randrange(3600) + self.rng.random()
            values.add(min(math.nextafter(float(DAY), 0), hour*3600+second))
        return sorted(values)


def trip_id(person, index):
    return f'{person}:trip:{index:04d}'


def hourly_fit(counts, probabilities):
    """Report marginal binomial uncertainty, never force coverage for small N."""
    total = sum(counts)
    if probabilities is None:
        return None
    return [dict(hour=h, observed=counts[h], expected=total*p,
                 standard_deviation=math.sqrt(total*p*(1-p)),
                 tolerance_6sigma_plus_1=6*math.sqrt(total*p*(1-p))+1,
                 within_tolerance=abs(counts[h]-total*p) <= 6*math.sqrt(total*p*(1-p))+1)
            for h,p in enumerate(probabilities)]


def load_temporal_policy(path, temporal_seed=None):
    return compile_temporal_policy(json.loads(Path(path).read_text(encoding='utf-8-sig')), temporal_seed)


def compile_temporal_policy(raw, temporal_seed=None):
    """Compile the one effective policy; no implicit override by agent catalogs.

    Absolute simulation times are never wrapped. Periodicity applies only to the
    synthetic intensity evaluated on a civil day, not to event/trip identities.
    """
    if not isinstance(raw, dict) or raw.get('schema_version') != POLICY_SCHEMA:
        raise ValueError('Unknown temporal policy schema')
    raw = json.loads(json.dumps(raw, allow_nan=False))
    if temporal_seed is not None:
        raw['temporal_seed'] = temporal_seed
    if type(raw.get('temporal_seed')) is not int:
        raise ValueError('temporal_seed must be an explicit integer')
    if raw.get('timezone') != 'America/Guatemala' or raw.get('departure_adaptation') != 'fixed':
        raise ValueError('Policy requires America/Guatemala and explicitly fixed departures')
    if raw.get('assumption_status') != 'synthetic_not_calibrated':
        raise ValueError('Temporal intensities must be identified as synthetic_not_calibrated')
    try:
        study_date = date.fromisoformat(raw['study_date'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('study_date must be an explicit ISO date') from None
    if study_date.weekday() >= 5:
        raise ValueError('This weekday experiment requires a Monday-Friday study date')
    durations = raw.get('windows', {})
    keys = ('warmup_seconds', 'study_seconds', 'post_demand_seconds', 'drain_seconds')
    if (set(durations) != set(keys) or
            any(type(durations[k]) is not int or durations[k] < 0 for k in keys) or
            durations['study_seconds'] != DAY or
            durations['warmup_seconds'] + durations['post_demand_seconds'] + durations['drain_seconds'] > 7*DAY):
        raise ValueError('Explicit nonnegative window durations required; study is exactly86400s; context max7days')
    intensity = raw.get('intensity', {})
    step = intensity.get('step_seconds')
    if type(step) is not int or not 1 <= step <= 900 or DAY % step:
        raise ValueError('Intensity resolution must divide86400 and be at most900seconds')
    expected = DAY//step+1
    def curve(values, name):
        if (not isinstance(values, list) or len(values) != expected or
                any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values) or
                not math.isclose(values[0], values[-1], rel_tol=0, abs_tol=1e-12) or
                not any(v > 0 for v in values[:-1])):
            raise ValueError(f'{name}: finite nonnegative periodic knots and positive integral required')
        try:
            if not math.isfinite(step*math.fsum(values[:-1])):
                raise ValueError(f'{name}: integral overflows')
        except OverflowError:
            raise ValueError(f'{name}: integral overflows') from None
    curve(intensity.get('knots'), 'intensity')
    if intensity.get('interpolation') != 'linear':
        raise ValueError('Intensity interpolation must be linear')
    profile_curves = raw.get('profile_multipliers', {})
    if not isinstance(profile_curves, dict):
        raise ValueError('profile_multipliers must be a mapping of profile names to periodic knots')
    for name, values in profile_curves.items():
        if not isinstance(name, str) or not name:
            raise ValueError('Invalid temporal profile name')
        curve(values, name)
        products=[a*b for a,b in zip(values,intensity['knots'])]
        curve(products,name+' effective')
        if math.fsum(products[:-1]) <= 0:
            raise ValueError(f'{name}: no positive intensity after multiplication')
    warmup, post, drain = (durations[k] for k in ('warmup_seconds', 'post_demand_seconds', 'drain_seconds'))
    study_end = warmup+DAY
    end_demand = study_end+post
    zone = ZoneInfo(raw['timezone'])
    civil_start = datetime.combine(study_date, time(), zone)
    technical_origin = civil_start-timedelta(seconds=warmup)
    civil_end = technical_origin+timedelta(seconds=end_demand+drain)
    if any((technical_origin+timedelta(seconds=t)).utcoffset() != civil_start.utcoffset()
           for t in (0, warmup, study_end, end_demand+drain)):
        raise ValueError('Policy assumes86400-second civil days; offset transition unsupported')
    windows = dict(warmup=dict(start_seconds=0,end_seconds=warmup),
                   study=dict(start_seconds=warmup,end_seconds=study_end),
                   post_demand=dict(start_seconds=study_end,end_seconds=end_demand),
                   drain=dict(start_seconds=end_demand,end_seconds=end_demand+drain),
                   simulation=dict(start_seconds=0,end_seconds=end_demand+drain))
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return dict(schema_version=POLICY_SCHEMA, policy_sha256=digest, configuration=raw,
                timezone=raw['timezone'], study_date=raw['study_date'], temporal_seed=raw['temporal_seed'],
                departure_adaptation='fixed', windows=windows,
                technical_origin_local=technical_origin.isoformat(), study_origin_local=civil_start.isoformat(),
                technical_end_local=civil_end.isoformat(), civil_utc_offset_seconds=int(civil_start.utcoffset().total_seconds()),
                intensity=raw['intensity'], profile_multipliers=profile_curves,
                context_count_method='Per-profile expected intensity mass relative to main; largest remainder, half-up total',
                assumptions=raw.get('assumptions', []))


def intensity_segments(policy, start, end, agent_type=None):
    """Piecewise linear densities on an absolute [start,end) interval."""
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
        raise ValueError('Invalid absolute intensity window')
    step = policy['intensity']['step_seconds']
    knots = policy['intensity']['knots']
    multipliers = policy.get('profile_multipliers', {}).get(agent_type)
    if multipliers is not None:
        knots = [a*b for a,b in zip(knots, multipliers)]
    origin = policy['windows']['study']['start_seconds']
    first = math.floor((start-origin)/step)
    for index in range(first, math.ceil((end-origin)/step)):
        left, right = origin+index*step, origin+(index+1)*step
        a, b = max(start,left), min(end,right)
        if b <= a:
            continue
        local = index % (len(knots)-1)
        v0, v1 = knots[local], knots[local+1]
        slope = (v1-v0)/step
        yield a,b,v0+slope*(a-left),v0+slope*(b-left)


def intensity_integral(policy, start, end, agent_type=None):
    return math.fsum((b-a)*(v0+v1)/2 for a,b,v0,v1 in intensity_segments(policy,start,end,agent_type))


class ContinuousDepartureSampler:
    """Exact inverse-CDF sampling of the linear density, independent per person."""
    def __init__(self, policy, agent_type, person_id, cohort='main'):
        window = policy['windows'][COHORT_WINDOWS[cohort]]
        self.parts = [part for part in intensity_segments(policy,window['start_seconds'],window['end_seconds'],agent_type)
                      if (part[2]+part[3]) > 0]
        if not self.parts:
            raise ValueError(f'No positive intensity for {cohort}/{agent_type}')
        self.cumulative = list(accumulate((b-a)*(v0+v1)/2 for a,b,v0,v1 in self.parts))
        self.rng = random.Random(json.dumps([POLICY_SCHEMA,policy['temporal_seed'],agent_type,person_id,cohort]))

    def sample(self, count=1):
        if type(count) is not int or count < 1:
            raise ValueError('Positive departure count required')
        values = set()
        while len(values) < count:
            target = self.rng.random()*self.cumulative[-1]
            index = min(len(self.parts)-1,bisect(self.cumulative,target))
            a,b,v0,v1 = self.parts[index]
            mass = target-(self.cumulative[index-1] if index else 0)
            slope = (v1-v0)/(b-a)
            if abs(slope) < 1e-15:
                offset = mass/v0
            elif mass == 0:
                offset = 0.
            else:
                offset = 2*mass/(v0+math.sqrt(max(0.,v0*v0+2*slope*mass)))
            values.add(min(math.nextafter(float(b),float(a)),a+max(0.,offset)))
        return sorted(values)


def context_allocations(main_counts, policy, canonical_order):
    """Context never changes N or the six main-cohort profile allocations."""
    study = policy['windows']['study']
    output = {}
    for cohort in ('warmup_context','post_context'):
        window = policy['windows'][COHORT_WINDOWS[cohort]]
        expected = {name:main_counts.get(name,0)*intensity_integral(policy,window['start_seconds'],window['end_seconds'],name)/
                    intensity_integral(policy,study['start_seconds'],study['end_seconds'],name) for name in canonical_order}
        target = math.floor(math.fsum(expected.values())+.5)
        counts = {name:math.floor(expected[name]) for name in canonical_order}
        ranked = sorted(canonical_order,key=lambda name: (-(expected[name]-counts[name]),canonical_order.index(name)))
        for name in ranked[:target-sum(counts.values())]: counts[name] += 1
        output[cohort] = dict(persons=target,expected_persons=math.fsum(expected.values()),
                              type_counts=counts,expected_by_type=expected)
    return output


def policy_spec(policy):
    study = policy['windows']['study']
    total = intensity_integral(policy,study['start_seconds'],study['end_seconds'])
    hourly = [intensity_integral(policy,study['start_seconds']+h*3600,study['start_seconds']+(h+1)*3600)/3600 for h in range(24)]
    return dict(profile=POLICY_SCHEMA,persons_are_N=False,trips_per_person=1,
                hourly_weights=hourly,hourly_probabilities=[v*3600/total for v in hourly],
                weight_source='explicit-synthetic-continuous-policy',policy_sha256=policy['policy_sha256'],
                demand_window=dict(study,end_exclusive=True),study_window=dict(study),
                simulation_window=dict(policy['windows']['simulation']),
                departure_intervals=[[0,policy['windows']['post_demand']['end_seconds']]],
                drain_seconds=policy['configuration']['windows']['drain_seconds'],
                scheduling='Fixed immutable principal and context departures; actual departures may occur later under QSim',
                rng='Independent per-person temporal seed, separate main allocation/spatial and context streams')


def main(argv=None):
    parser=argparse.ArgumentParser(description='Validate a synthetic continuous weekday policy without generating population or running MATSim')
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--temporal-seed',type=int)
    parser.add_argument('--agents',type=int,required=True,help='Principal cohort N; validation and allocation only')
    parser.add_argument('--agent-catalog',type=Path,required=True)
    parser.add_argument('--sensitivity-hours',default='3,6,12',help='Warmup/post-demand duration probes; no simulations are executed')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        from simz1_agent_types import load_catalog,allocation_counts
        if args.agents < 1:
            raise ValueError('Principal N must be positive')
        policy=load_temporal_policy(args.policy,args.temporal_seed)
        catalog=load_catalog(args.agent_catalog)
        if set(policy['profile_multipliers'])-set(catalog['profiles']):
            raise ValueError('Temporal multiplier references unknown catalog profile')
        counts=allocation_counts(args.agents,catalog)
        sensitivity=[]
        for hour in map(float,args.sensitivity_hours.split(',')):
            if not math.isfinite(hour) or hour < 0 or hour*3600 != int(hour*3600):
                raise ValueError('Sensitivity hours must be finite nonnegative whole seconds')
            raw=json.loads(json.dumps(policy['configuration']))
            raw['windows']['warmup_seconds']=int(hour*3600)
            raw['windows']['post_demand_seconds']=int(hour*3600)
            probe=compile_temporal_policy(raw)
            sensitivity.append(dict(warmup_hours=hour,post_demand_hours=hour,
                context=context_allocations(counts,probe,catalog['canonical_order']),
                technical_origin_local=probe['technical_origin_local']))
        result=dict(status='valid',principal_cohort_persons=args.agents,principal_type_counts=counts,
                    policy=policy,context=context_allocations(counts,policy,catalog['canonical_order']),
                    hourly_probabilities=policy_spec(policy)['hourly_probabilities'],
                    sensitivity=sensitivity,sensitivity_scope='Intensity integration only; does not establish QSim equilibration or absence of censoring')
        output=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(output,encoding='utf-8')
        print(output)
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Temporal policy validation failed: '+str(error),file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
