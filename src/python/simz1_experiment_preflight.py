"""Fail-closed six-profile experiment preflight; reads configuration, creates no run."""
import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from simz1_agent_types import active_types, allocation_counts, catalog_manifest
from simz1_agent_demand import generation_catalog, validate_road_access
from simz1_result_quality import PROFILES
from simz1_run import parameters
from simz1_temporal import POLICY_SCENARIO_VERSION
from simz1_lane_validation import audit_configuration


def check(config, catalog, minimum, maximum, origin_policy, storage_policy, transit_service=None, transit_service_date=None, accept_transit_route_assumptions=False,
          temporal_policy=None, temporal_seed=None, freight_service=None, freight_service_date=None,
          freight_vehicles=None, no_freight_transport=False, whole_vehicle_reservation=False, qsim_threads=1, destination_policy="legacy-gaussian-v1",
          od_mode='network', zone_boundary=None, od_access_catalog=None, od_mix_file=None, seed=20261023,
          experiment_spec=None, experiment_scenario=None, iterations=1):
    balanced = None
    configuration_contract = None
    if experiment_spec is not None:
        from simz1_scale_contract import experiment, require_base_inputs
        selected = experiment(experiment_spec, experiment_scenario)
        if selected.get('base_scenario_identity'):
            from simz1_configuration_contract import expected_from_selection, retained_iterations
            configuration = expected_from_selection(selected)
            configuration_contract = dict(configuration=configuration, **retained_iterations(configuration))
        if od_mode != 'balanced-gateway-v1': raise ValueError('Experiment requires balanced-gateway-v1')
        require_base_inputs(selected, source_config=config, agent_catalog=catalog, transit_service=transit_service,
                            freight_service=freight_service, zone_boundary=zone_boundary,
                            od_access_catalog=od_access_catalog, od_mix_file=od_mix_file)
        if transit_service_date != selected['service_date'] or freight_service_date != selected['service_date']:
            raise ValueError('Experiment service dates differ')
    if od_mode == 'balanced-gateway-v1':
        from simz1_scale_contract import require_scale
        require_scale(minimum, seed, iterations, experiment_spec, experiment_scenario)
        from simz1_balanced_launch import identity
        identity(zone_boundary, od_access_catalog, od_mix_file)
        if (origin_policy != 'lane-length-access-v1' or minimum != maximum or
                not whole_vehicle_reservation or qsim_threads != 1 or
                storage_policy != 'strict-receiver-v1' or temporal_policy is not None or
                not transit_service or not freight_service or no_freight_transport):
            raise ValueError('Balanced OD requires exact N, reviewed access origins, unchanged services, times and physical reservations')
    elif od_mode != 'network' or any(v is not None for v in (zone_boundary, od_access_catalog, od_mix_file)) or origin_policy == 'lane-length-access-v1':
        raise ValueError('OD options incompatible with network; no implicit fallback')
    if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum <= 250000:
        raise ValueError('Se requiere 0 <= minimo <= maximo <= 250000')
    if whole_vehicle_reservation and (qsim_threads != 1 or storage_policy != 'strict-receiver-v1'):
        raise ValueError('Reserva fisica por corredor requiere QSim1 y strict-receiver-v1')
    config, catalog = Path(config).resolve(strict=True), Path(catalog).resolve(strict=True)
    # Audit the actual source XML before service checks or any scheduled-demand
    # iterator. Preparation uses this same gate and evidence, then rechecks its
    # derived transit files before publishing a manifest.
    lane_audit = audit_configuration(config,
        osm_path=config.parent/'map.osm' if od_mode == 'balanced-gateway-v1' else None)
    source = generation_catalog(catalog, mode='montecarlo', temporal_profile=None, hourly_weights=None, drain_seconds=0)
    if source.get("destination_policy", "legacy-gaussian-v1") != destination_policy:
        raise ValueError("Destination policy does not match the versioned catalog")
    from simz1_demand_composition import contract, split, freight_options
    composition_policy = contract(source)
    compositions = ({str(n): split(n, source) for n in dict.fromkeys((minimum, maximum))}
                    if composition_policy is not None else None)
    if composition_policy is None and minimum == 0:
        raise ValueError('Zero demand requires the explicit non-public composition catalog')
    if composition_policy is not None and temporal_policy is not None:
        raise ValueError('Non-public composition uses the existing single-day freight calendar; continuous multi-day policy is not supported')
    private_bounds = [compositions[str(n)]['private_vehicles'] if compositions else n for n in (minimum, maximum)]
    active = set(active_types(source))
    if active != set(PROFILES):
        raise ValueError(f'Este experimento requiere exactamente tres carros y tres motos, no {sorted(active)}')
    for n in private_bounds:
        counts = allocation_counts(n, source)
        if n >= len(PROFILES) and any(counts[k] <= 0 for k in PROFILES):
            raise ValueError(f'N={n} no representa los seis perfiles. Aumente la prueba pequena.')
    values = parameters(config)
    root = ET.parse(config).getroot()
    temporal = None
    if temporal_policy is not None:
        from simz1_temporal import load_temporal_policy
        temporal = load_temporal_policy(temporal_policy, temporal_seed=temporal_seed)
        unknown = set(temporal['profile_multipliers']) - set(source['profiles'])
        if unknown:
            raise ValueError('Perfiles temporales desconocidos: '+', '.join(sorted(unknown)))
        if transit_service_date is not None and transit_service_date != temporal['study_date']:
            raise ValueError('La fecha de transporte difiere de la jornada temporal')
        transit_service_date = temporal['study_date']
        strategies = [p.get('value') for p in root.findall("module[@name='strategy']/parameterset/param[@name='strategyName']")]
        if any(s not in ('ChangeExpBeta', 'ReRoute', 'SelectExpBeta', 'BestScore', 'KeepLastSelected') for s in strategies):
            raise ValueError('La politica temporal fixed rechaza estrategias que puedan cambiar horarios: '+str(strategies))
    elif temporal_seed is not None:
        raise ValueError('--temporal-seed requiere --temporal-policy')
    network_param = root.find("module[@name='network']/param[@name='inputNetworkFile']")
    if network_param is None: raise ValueError('Falta network.inputNetworkFile')
    network = (config.parent/network_param.get('value')).resolve(strict=True)
    validate_road_access(network, source)
    if values.get('zona1WithinDayRouting.routingPolicy','fastest-time') != 'fastest-time':
        raise ValueError('El catalogo requiere ruteo fastest-time configurado')
    if values.get('qsim.linkDynamics','FIFO') != 'FIFO' or values.get('qsim.trafficDynamics','queue') != 'queue':
        raise ValueError('Perfiles v1 requieren queue/FIFO; no se finge filtrado de motos')
    if values.get('transit.useTransit') == 'true':
        raise ValueError('Experimento seis perfiles: use un lanzador de flota para un servicio publico habilitado')
    transit = None
    if transit_service is not None:
        from simz1_weekday_transit import preflight
        transit = preflight(config, transit_service, transit_service_date, accept_transit_route_assumptions,
                            temporal_policy=temporal)
    freight = None
    if compositions is not None:
        from simz1_freight import preflight as freight_preflight
        by_total = {}
        for total, mix in compositions.items():
            path, day, number, disabled = freight_options(mix, freight_service, freight_service_date,
                                                         freight_vehicles, no_freight_transport)
            item = (freight_preflight(config, path, day, number, temporal) if path is not None else
                    dict(enabled=False, vehicles_configured=0, departures_scheduled=0, reason='rounded_freight_quota_zero'))
            item.update(independent_of_private_demand=False, included_in_non_public_total=True)
            by_total[total] = item
        freight = by_total[str(minimum)] if minimum == maximum else dict(
            enabled=any(v['enabled'] for v in by_total.values()), quantity_basis='derived_after_single_N_draw',
            by_total_bound=by_total)
    else:
        if no_freight_transport and (freight_service or freight_service_date or freight_vehicles is not None):
            raise ValueError('Disabled freight conflicts with service options')
        if freight_service:
            from simz1_freight import preflight as freight_preflight
            freight = freight_preflight(config, freight_service, freight_service_date, freight_vehicles, temporal)
        elif freight_service_date or freight_vehicles is not None:
            raise ValueError('Freight options require a service')
    catalog_temporal = source.get('temporal_demand', {'source':'catalog_intervals'})
    effective_temporal = catalog_temporal
    if temporal is not None:
        from simz1_temporal import policy_spec, intensity_integral
        effective_temporal = policy_spec(temporal)
        study = temporal['windows']['study']
        probabilities_by_type = {}
        for kind in sorted(active):
            total = intensity_integral(temporal, study['start_seconds'], study['end_seconds'], kind)
            probabilities_by_type[kind] = [intensity_integral(temporal,
                study['start_seconds'] + hour*3600, study['start_seconds'] + (hour+1)*3600, kind)/total
                for hour in range(24)]
        by_population = {}
        for n in dict.fromkeys((minimum, maximum)):
            counts = allocation_counts(n, source)
            by_population[str(n)] = [math.fsum(counts[k]*values[hour]
                for k, values in probabilities_by_type.items())/n for hour in range(24)]
        effective_temporal.update(per_type_hourly_probabilities=probabilities_by_type,
            catalog_temporal_override='Explicit continuous policy replaces catalog departure windows and hourly weights')
        if minimum == maximum:
            probabilities = by_population[str(minimum)]
            effective_temporal.update(hourly_weights=probabilities, hourly_probabilities=probabilities,
                hourly_weights_kind='Normalized main-cohort mixture probability mass per equal3600-second interval')
        else:
            # N is not selected by preflight. Do not report a base curve as the
            # effective population mixture when profile-specific curves differ.
            effective_temporal.pop('hourly_weights')
            effective_temporal.pop('hourly_probabilities')
            effective_temporal.update(hourly_probabilities_by_population_bound=by_population,
                hourly_weights_kind='Mixture depends on selected N; per-profile curves and range-bound allocations shown')
    if od_mode == 'balanced-gateway-v1':
        from simz1_balanced_launch import check as check_balanced
        if (transit['fleet_by_system'] != {'transmetro':176, 'tubus':93} or
                (minimum>0 and (freight.get('service_version') != 'weekday-compact-v3' or
                freight['native_dimensions_m'] != dict(length_m=8, width_m=2.3)))):
            raise ValueError('Balanced OD requires 269 preserved buses and compact-v3 freight 8 x 2.3 m')
        balanced = check_balanced(config, catalog, minimum, zone_boundary, od_access_catalog, od_mix_file, seed,
            transit_service=transit_service, transit_service_date=transit_service_date,
            accept_transit_route_assumptions=accept_transit_route_assumptions,
            experiment_spec=experiment_spec,experiment_scenario=experiment_scenario,iterations=iterations)
        lane_audit = balanced['lane_configuration_validation']
        balanced['report']['buses_additional'] = dict(total=269, transmetro=176, tubus=93)
    return dict(public_transport=transit, freight_transport=freight, balanced_od=balanced, od_mode=od_mode,
        configuration_contract=configuration_contract,
        lane_configuration_validation=lane_audit,
        status='preflight_pass', source_config=str(config), agent_catalog=str(catalog),
        scenario_version=POLICY_SCENARIO_VERSION if temporal else source['scenario_version'],
        catalog_scenario_version=source['scenario_version'], active_profiles=sorted(active),
        normalized_weights=catalog_manifest(source)['normalized_weights'],
        minimum_allocation=allocation_counts(private_bounds[0],source), maximum_allocation=allocation_counts(private_bounds[1],source),
        demand_composition_by_bound=compositions,
        N_denominator='non_public_vehicles' if compositions is not None else 'private_persons',
        origin_policy=origin_policy, destination_policy=destination_policy, storage_policy=storage_policy,
        physical_occupancy=dict(enabled=whole_vehicle_reservation,
            policy='corridor-length-v1' if whole_vehicle_reservation else 'native-pcu',
            minimum_gap_m=.10 if whole_vehicle_reservation else None,
            qsim_threads=qsim_threads, positions_observed=False,
            evidence='requested_configuration_only'),
        temporal_demand=effective_temporal, temporal_policy=temporal,
        catalog_temporal_demand=catalog_temporal,
        omitted_categories={'TransportePesado':('included in N through dedicated freight service; not generated by the private router' if compositions is not None else 'separate freight service; private catalog weight remains 0'),
                            'TransportePublico':'separate service, not silently generated'},
        limitations=['Synthetic scenario, not calibrated Guatemala demand.',
                     'Motorcycles are effective vehicle types on QSim car mode, not car labels; FIFO does not implement filtering.',
                     'No simulation performed and no network capacity/low-censoring guarantee.'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--transit-service',type=Path)
    p.add_argument('--freight-service',type=Path)
    p.add_argument('--freight-service-date')
    p.add_argument('--freight-vehicles',type=int)
    p.add_argument('--no-freight-transport',action='store_true')
    p.add_argument('--transit-service-date')
    p.add_argument('--accept-transit-route-assumptions',action='store_true')
    p.add_argument('--temporal-policy',type=Path)
    p.add_argument('--temporal-seed',type=int)
    p.add_argument('--agent-catalog',type=Path,required=True)
    p.add_argument('--min-agents',type=int,required=True)
    p.add_argument('--max-agents',type=int,required=True)
    p.add_argument('--destination-policy',choices=['legacy-gaussian-v1','lane-length-destinations-v1'],default='legacy-gaussian-v1')
    p.add_argument('--origin-policy',choices=['legacy-corridors','uniform-nodes-v1','lane-length-access-v1'],required=True)
    p.add_argument('--od-mode', choices=['network','balanced-gateway-v1'], default='network')
    p.add_argument('--zone-boundary', type=Path)
    p.add_argument('--od-access-catalog', type=Path)
    p.add_argument('--od-mix-file', type=Path)
    p.add_argument('--seed', type=int, default=20261023)
    p.add_argument('--experiment-spec',type=Path)
    p.add_argument('--experiment-scenario')
    p.add_argument('--iterations',type=int,default=1)
    p.add_argument('--storage-policy',choices=['strict-receiver-v1','matsim15-native'],required=True)
    p.add_argument('--whole-vehicle-reservation', action=argparse.BooleanOptionalAction, default=False)
    p.add_argument('--qsim-threads', type=int, choices=(1,4), default=1)
    a=p.parse_args()
    try:
        print(json.dumps(check(a.config,a.agent_catalog,a.min_agents,a.max_agents,a.origin_policy,a.storage_policy,a.transit_service,a.transit_service_date,a.accept_transit_route_assumptions,a.temporal_policy,a.temporal_seed,
                               a.freight_service,a.freight_service_date,a.freight_vehicles,a.no_freight_transport,
                               a.whole_vehicle_reservation,a.qsim_threads,a.destination_policy,
                               a.od_mode,a.zone_boundary,a.od_access_catalog,a.od_mix_file,a.seed,
                               a.experiment_spec,a.experiment_scenario,a.iterations),
                         indent=2,ensure_ascii=False,allow_nan=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as e:
        if hasattr(e,'diagnostic'):
            print(json.dumps(e.diagnostic,indent=2,ensure_ascii=False,allow_nan=False),file=sys.stderr)
        print(f'Preflight rechazado: {e}',file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
