"""Prepare a versioned type allocation, never a MATSim run or fake transit service."""
import argparse
from collections import Counter
import json
from pathlib import Path

from simz1_agent_types import load_catalog, allocate_types, sample_departures, execution_blockers, catalog_manifest, ROAD_DEFAULT_CATALOG
from simz1_agent_demand import active_types, assignment_record
from simz1_population import population_spec, resolve_demand_seed, positive_integer
from simz1_run import sha256, atomic_json
from simz1_run_directory import check_new_directory, create_run_directory


def prepare_agents(output_dir, agents, seed=None, *, catalog_path=None, trips_per_person=1, massive=False):
    output_dir = check_new_directory(output_dir)
    population_spec('montecarlo', agents=agents, massive=massive)
    if type(trips_per_person) is not int or trips_per_person < 1:
        raise ValueError('trips_per_person debe ser entero positivo')
    # Future allocations default to the explicit road-only revision. Loading an
    # old catalog is still possible by path for historical proposal reproduction.
    catalog = load_catalog(catalog_path or ROAD_DEFAULT_CATALOG)
    seed, seed_selection = resolve_demand_seed(seed)
    kinds = allocate_types(agents, seed, catalog)
    blockers = execution_blockers(active_types(catalog), catalog)
    counts = Counter(kinds)
    output_dir = create_run_directory(output_dir, parent=output_dir.parent)
    catalog_file = output_dir/'agent-catalog.json'
    atomic_json(catalog_file, catalog)
    ledger = output_dir/'agent-types.jsonl'
    with ledger.open('x', encoding='utf-8', newline='\n') as output:
        for index, kind in enumerate(kinds, 1):
            ident = f'z1_{index:05}'
            departures = sample_departures(kind, trips_per_person, seed, ident, catalog)
            output.write(json.dumps(assignment_record(ident, kind, departures, catalog, prepared_only=True),
                                    ensure_ascii=False, sort_keys=True, allow_nan=False)+'\n')
    manifest = dict(schema_version=1, artifact_kind='simz1-agent-allocation-not-a-run',
                    status='blocked' if blockers else 'allocation_ready', runnable=False,
                    demand_seed=seed, seed_selection=seed_selection,
                    requested_persons=agents, allocated_persons=len(kinds), planned_trips=agents*trips_per_person,
                    person_counts={name: counts[name] for name in catalog['profiles']},
                    passenger_persons=counts['TransportePublico'], transit_service_vehicles=None,
                    instantiated_vehicles=0,
                    allocation_method=catalog['allocation']['rounding'] + '_canonical_ties_then_seeded_shuffle',
                    agent_configuration=catalog_manifest(catalog), blockers=blockers,
                    artifacts={name: dict(path=path.name, sha256=sha256(path))
                               for name, path in (('catalog', catalog_file), ('person_types', ledger))},
                    limitations=['Allocation only: no OD, car plans, transit lines or service vehicles generated.',
                                 'Scheduled departures do not guarantee observed QSim departure/arrival times.',
                                 'All time windows are scenario assumptions, not confirmed PMT regulations.'])
    atomic_json(output_dir/'agent-plan-manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='Carpeta nueva; no se reutilizan corridas')
    parser.add_argument('--agents', type=positive_integer, required=True, help='Personas viales; el catalogo futuro excluye transporte publico de N')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--catalog', type=Path, help='Predeterminado agent-types-road-v1.json sintetico; rutas antiguas solo para reproducir propuestas historicas')
    parser.add_argument('--trips-per-person', type=positive_integer, default=1)
    parser.add_argument('--massive', action='store_true')
    args = parser.parse_args()
    try:
        result = prepare_agents(args.output_dir, args.agents, args.seed, catalog_path=args.catalog,
                                trips_per_person=args.trips_per_person, massive=args.massive)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'No se pudo preparar asignacion: {exc}\n')
    print(json.dumps({key: result[key] for key in ('status', 'runnable', 'allocated_persons', 'person_counts', 'blockers')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
