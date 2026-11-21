"""Future road-only scenarios. Historical six-category catalogs stay unchanged.

Weights are synthetic configuration, never observed shares. Allocation first
preserves the former road categories, then splits only their motorcycle quota.
"""
from fractions import Fraction
import math

SCHEMA = 'simz1-road-profiles-v1'
BASE = ('Normal', 'Motociclista', 'Liebre', 'Tortuga', 'TransportePesado')
MOTOS = ('MotocicletaLenta', 'Motociclista', 'MotocicletaRapida')
TYPES = ('Normal', *MOTOS, 'Liebre', 'Tortuga', 'TransportePesado')
IDENTITIES = {
    'Normal': ('carro', 'normal', 'Carro'),
    'Liebre': ('carro', 'liebre', 'Carro liebre'),
    'Tortuga': ('carro', 'tortuga', 'Carro Tortuga'),
    'MotocicletaLenta': ('moto', 'tortuga', 'Moto tortuga'),
    'Motociclista': ('moto', 'normal', 'Moto'),
    'MotocicletaRapida': ('moto', 'liebre', 'Moto Liebre'),
    'TransportePesado': ('pesado', 'normal', 'Transporte pesado'),
}


def positive(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name}: expected finite positive number')


def weights(value, order):
    if not isinstance(value, dict) or set(value) != set(order):
        raise ValueError(f'Explicit weights required for {order}')
    if any(type(v) is not int or v < 0 for v in value.values()) or sum(value.values()) <= 0:
        raise ValueError('Weights must be nonnegative integers with positive total')


def validate(catalog):
    if catalog.get('schema_version') != SCHEMA or catalog.get('canonical_order') != list(TYPES):
        raise ValueError('Unknown road catalog schema/types')
    if (catalog.get('denominator') != 'persons' or catalog.get('horizon_seconds') != 86400 or
            catalog.get('assumption_status') != 'synthetic_not_observed' or
            not isinstance(catalog.get('scenario_version'), str) or not catalog['scenario_version'].strip()):
        raise ValueError('Road catalog requires explicit new scenario version, synthetic provenance and 24h person denominator')
    allocation = catalog.get('allocation', {})
    if allocation.get('rounding') != 'hierarchical_largest_remainder' or allocation.get('tie_break') != 'canonical_order':
        raise ValueError('Road allocation requires hierarchical largest remainders')
    weights(allocation.get('road_weights'), BASE)
    weights(allocation.get('motorcycle_weights'), MOTOS)
    if allocation.get('family_first') is not None and allocation.get('family_first') is not True:
        raise ValueError('family_first must be true or absent')
    from simz1_demand_composition import contract
    contract(catalog)
    # This provenance describes the old proposal, not the user's new weights.
    if allocation.get('removed_public_transport_weight') != 10 or allocation.get('previous_total_weight') != 100:
        raise ValueError('Retain explicit provenance of removed PT 10/100')
    temporal = catalog.get('temporal_demand')
    if temporal is not None:
        values = temporal.get('hourly_weights') if isinstance(temporal, dict) else None
        if (not isinstance(temporal, dict) or temporal.get('source') != 'explicit-synthetic-hourly-v1'
                or not isinstance(values, list) or len(values) != 24
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values)
                or not math.isfinite(math.fsum(values)) or math.fsum(values) <= 0):
            raise ValueError('Road temporal_demand requires 24 finite nonnegative synthetic hourly weights')
    profiles = catalog.get('profiles')
    if not isinstance(profiles, dict) or set(profiles) != set(TYPES):
        raise ValueError('Exactly seven road types required; public transport is a separate service')
    for name, spec in profiles.items():
        if not isinstance(spec, dict):
            raise ValueError(f'{name}: expected profile object')
        if tuple(spec.get(k) for k in ('family', 'driving_profile', 'label')) != IDENTITIES[name]:
            raise ValueError(f'{name}: incompatible family/profile/label')
        if (spec.get('population_role'), spec.get('mode'), spec.get('vehicle_type')) != ('driver', 'car', name):
            raise ValueError(f'{name}: invalid road vehicle identity')
        for key in ('pcu', 'maximum_speed_kmh'):
            positive(spec.get(key), f'{name}.{key}')
        if spec.get('routing_preference') not in ('fastest-time', 'shortest-distance'):
            raise ValueError(f'{name}: unsupported routing policy')
        dimensions = spec.get('dimensions', {})
        for key in ('length_m', 'width_m'):
            positive(dimensions.get(key), f'{name}.{key}')
        if (dimensions.get('assumed') is not True or not isinstance(dimensions.get('source'), str) or
                not dimensions['source'].strip()):
            raise ValueError(f'{name}: this synthetic catalog requires declared assumed dimensions')
        if spec.get('acceleration') != {'model': 'not_integrated_by_QSim', 'm_s2': None}:
            raise ValueError(f'{name}: no physical acceleration model has been implemented')
        access = spec.get('access', {})
        if access != dict(requires_authorized_links=name == 'TransportePesado', authorized_link_ids=[],
                          municipal_status='not_claimed', source=None):
            raise ValueError(f'{name}: unsupported access policy; no unimplemented restrictions may be activated')
        if spec.get('departure_intervals') != [dict(start_seconds=0, end_seconds=86400, weight=1)]:
            raise ValueError(f'{name}: no municipal time windows are established in this schema')
    speeds = [profiles[k]['maximum_speed_kmh'] for k in MOTOS]
    if not speeds[0] < speeds[1] < speeds[2]:
        raise ValueError('Motorcycle maximum speeds must satisfy tortuga < normal < liebre')
    if catalog.get('transit_service') != dict(in_random_population=False, implementation_status='separate_service_required'):
        raise ValueError('Public transport must remain outside N')
    return catalog


def apportion(count, values, order):
    total = sum(values.values())
    quotients = [divmod(count * values[k], total) for k in order]
    result = {k: quotients[i][0] for i, k in enumerate(order)}
    ranking = sorted(range(len(order)), key=lambda i: (-quotients[i][1], i))
    for i in ranking[:count - sum(result.values())]:
        result[order[i]] += 1
    return result


def counts(count, catalog):
    validate(catalog)
    if type(count) is not int or count < 0:
        raise ValueError('count must be a nonnegative integer')
    allocation = catalog['allocation']
    road = allocation['road_weights']
    if allocation.get('family_first'):
        cars = ('Normal', 'Liebre', 'Tortuga')
        family = apportion(count, {'carro': sum(road[k] for k in cars),
                                   'moto': road['Motociclista'], 'pesado': road['TransportePesado']},
                           ('carro', 'moto', 'pesado'))
        result = apportion(family['carro'], {k: road[k] for k in cars}, cars)
        result['TransportePesado'] = family['pesado']
        result.update(apportion(family['moto'], allocation['motorcycle_weights'], MOTOS))
    else:
        result = apportion(count, road, BASE)
        result.update(apportion(result.pop('Motociclista'), allocation['motorcycle_weights'], MOTOS))
    return {k: result[k] for k in TYPES}


def probabilities(catalog):
    allocation = catalog['allocation']
    road, moto = allocation['road_weights'], allocation['motorcycle_weights']
    result = {k: Fraction(v, sum(road.values())) for k, v in road.items()}
    moto_share = result.pop('Motociclista')
    result.update({k: moto_share * Fraction(v, sum(moto.values())) for k, v in moto.items()})
    return {k: result[k] for k in TYPES}


def blockers(names, catalog):
    validate(catalog)
    if set(names) - set(TYPES):
        raise ValueError('Unknown road type; buses cannot be assigned within N')
    return (['TransportePesado: route access enforcement is not implemented; explicit dimensions/PCU/speed '
             'are a synthetic proposal, not authorization or effective simulated parameters']
            if 'TransportePesado' in names else [])


def normalized_weights(catalog):
    allocation = catalog['allocation']
    return dict(removed_public_transport='10/100',
                road_denominator=sum(allocation['road_weights'].values()),
                road_fractions={k: str(Fraction(v, sum(allocation['road_weights'].values())))
                                for k, v in allocation['road_weights'].items()},
                type_fractions={k: str(v) for k, v in probabilities(catalog).items()},
                assumption_status='synthetic_not_observed')
