"""Versioned non-public vehicle quotas; buses remain a separately fixed service.

N includes cars, motorcycles and freight. Internal planned_persons continues to
count private drivers, so historical manifests and transit accounting retain
what their fields mean. No observed/calibrated traffic shares are claimed.
"""
from fractions import Fraction
import json
from pathlib import Path

SCHEMA = 'simz1-nonpublic-composition-v1'
FAMILIES = ('carro', 'moto', 'pesado')
CARS = ('Normal', 'Liebre', 'Tortuga')
MOTOS = ('MotocicletaLenta', 'Motociclista', 'MotocicletaRapida')


def contract(catalog):
    value = catalog.get('non_public_demand')
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get('schema_version') != SCHEMA or
            value.get('denominator') != 'non_public_vehicles' or
            value.get('public_transport_in_total') is not False or
            value.get('empirical_calibration') is not False):
        raise ValueError('Invalid non-public demand contract; buses must remain outside N')
    weights = value.get('family_weights', {})
    if (set(weights) != set(FAMILIES) or
            any(type(v) is not int or v <= 0 for v in weights.values())):
        raise ValueError('Non-public family weights must be explicit positive integers')
    limits = value.get('default_range')
    if (not isinstance(limits, list) or len(limits) != 2 or
            any(type(n) is not int for n in limits) or not 0 < limits[0] <= limits[1] <= 250000):
        raise ValueError('Invalid non-public default_range')
    allocation = catalog['allocation']
    if allocation.get('family_first') is not True or allocation['road_weights']['TransportePesado'] != 0:
        raise ValueError('Freight must use its dedicated route/window service, never private routing')
    road = allocation['road_weights']
    if sum(road[k] for k in CARS) <= 0 or road['Motociclista'] <= 0:
        raise ValueError('Non-public demand needs positive private car and motorcycle weights')
    if Fraction(sum(road[k] for k in CARS), road['Motociclista']) != Fraction(weights['carro'], weights['moto']):
        raise ValueError('Private catalog and non-public car/motorcycle ratio disagree')
    if value.get('rounding') != 'largest_remainder_private_freight_then_families_then_profiles':
        raise ValueError('Unsupported non-public quota rounding')
    return value


def split(total, catalog):
    """Hierarchical largest remainders, with deterministic canonical ties.

    First reserve freight vs private; then split private into car/motorcycle;
    finally split the two families by their unchanged internal profile weights.
    All integer counts add exactly to N, including N=0.
    """
    from simz1_road_catalog import apportion, counts
    policy = contract(catalog)
    if policy is None:
        raise ValueError('A non-public composition catalog is required')
    if type(total) is not int or not 0 <= total <= 250000:
        raise ValueError('Non-public N must be an integer in 0..250000')
    weights = policy['family_weights']
    quota = apportion(total, {'private': weights['carro'] + weights['moto'],
                              'freight': weights['pesado']}, ('private', 'freight'))
    private_types = counts(quota['private'], catalog)
    families = {'carro': sum(private_types[k] for k in CARS),
                'moto': sum(private_types[k] for k in MOTOS), 'pesado': quota['freight']}
    return dict(schema_version=SCHEMA, denominator='non_public_vehicles',
                total_non_public_vehicles=total, private_vehicles=quota['private'],
                freight_vehicles=quota['freight'], family_counts=families,
                private_profile_counts=private_types, family_weights=dict(weights),
                family_fractions={k: str(Fraction(weights[k], sum(weights.values()))) for k in FAMILIES},
                realized_family_fractions={k: families[k]/total if total else None for k in FAMILIES},
                rounding=policy['rounding'], public_transport_in_total=False,
                public_transport_quantity='unchanged configured service, independent of N',
                empirical_calibration=False,
                interpretation='Requested synthetic vehicle population, NOT observed simultaneous occupancy or calibrated daily counts')


def freight_options(composition, service, service_date, override, disabled):
    """Return effective dedicated-service options, rejecting silent double counts."""
    n = composition['freight_vehicles']
    if override is not None and (type(override) is not int or override != n):
        raise ValueError(f'Freight is included in N: expected {n}, not {override}; omit --freight-vehicles/-FreightVehicles')
    if disabled and n:
        raise ValueError('This composition includes freight; --no-freight-transport would change the requested percentages')
    if n and service is None:
        raise ValueError('Non-public composition requires --freight-service for its heavy-vehicle quota')
    if not n:
        return None, None, None, True
    return service, service_date, n, False


def validate_manifest(directory, manifest, private_ids, freight_contract):
    """Validate new quota evidence against fingerprinted inputs and actual actors."""
    record = manifest.get('demand_composition')
    if record is None:
        return  # Do not reinterpret any historical run.
    from simz1_run import checked_path
    from simz1_agent_types import load_catalog
    catalog = load_catalog(checked_path(directory, manifest['agent_configuration']['catalog_artifact']))
    snapshot = json.loads(checked_path(directory, manifest['inputs']['input:demand-composition.json']).read_text(encoding='utf-8'))
    expected = split(record['total_non_public_vehicles'], catalog)
    if snapshot != record or any(record.get(k) != v for k, v in expected.items()):
        raise ValueError('Non-public composition differs from its catalog or input snapshot')
    if len(private_ids) != expected['private_vehicles'] or len(freight_contract) != expected['freight_vehicles']:
        raise ValueError('Non-public composition does not match private/freight actors')
    if manifest['counts'].get('non_public_vehicles_configured') != expected['total_non_public_vehicles']:
        raise ValueError('Non-public manifest total mismatch')
    if manifest['agent_configuration']['realized_person_counts'] != expected['private_profile_counts']:
        raise ValueError('Non-public profile counts differ from configured largest remainders')
    freight = manifest.get('freight_transport', {})
    if expected['freight_vehicles'] and (not freight.get('enabled') or
            freight.get('vehicles_configured') != expected['freight_vehicles'] or
            freight.get('departures_scheduled') != expected['freight_vehicles']):
        raise ValueError('Non-public freight quota missing or counted more than once')
    return expected


def main(argv=None):
    """Read-only quota preview; never generates XML, runs MATSim or writes state."""
    import argparse
    import sys
    from simz1_agent_types import load_catalog
    from simz1_weekday_transit import DEFAULT, load_policy
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agents', type=int, required=True, help='Total no publico, incluyendo carga')
    parser.add_argument('--catalog', type=Path, default=root/'scenarios/zona1/agent-types-nonpublic-v1.json')
    parser.add_argument('--transit-service', type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        result = split(args.agents, load_catalog(args.catalog))
        # Validate per-service allocations too; this is only a read-only preview.
        transit, service_path = load_policy(args.transit_service, accept_route_assumptions=True)
        fleet = transit['fleet_counts']
        if any(type(n) is not int or n < 0 for n in fleet.values()):
            raise ValueError('Invalid configured public fleet')
        result['public_fleet_configured'] = fleet
        result['public_service'] = str(service_path)
        result['public_scenario_version'] = transit['scenario_version']
        result['all_vehicles_configured'] = args.agents + sum(fleet.values())
        result['status'] = 'allocation_preview_only_not_simulated'
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f'Composition preview refused: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
