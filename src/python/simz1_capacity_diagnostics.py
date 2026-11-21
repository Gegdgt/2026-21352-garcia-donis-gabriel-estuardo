"""Read-only SimZ1 capacity screening; never generates demand or starts QSim.

Default: small recorded evidence and network/config only, not plans/events.
--events explicitly audits at most 1000 planned people, with a strict 24 h cut.
"""
import argparse
import gzip
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_run import MANIFEST, checked_path, load_manifest, parameters, seconds, sha256


def finite(value, name, minimum=0):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{name}: falta un numero finito') from None
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f'{name}: fuera de rango')
    return result


def read_network(path, flow_factor=1):
    """Configured link capacity is already aggregated over lanes, in PCU/capperiod."""
    factor = finite(flow_factor, 'flowCapacityFactor')
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        root = ET.parse(stream).getroot()
    container = root.find('links')
    if container is None or container.get('capperiod') is None:
        raise ValueError('Red sin links/capperiod explicito; no se asume una hora')
    period = finite(seconds(container.get('capperiod')), 'capperiod', math.nextafter(0., 1.))
    nodes = {node.get('id') for node in root.findall('nodes/node')}
    links = {}
    for link in container.findall('link'):
        ident = link.get('id')
        if not ident or ident in links or link.get('from') not in nodes or link.get('to') not in nodes:
            raise ValueError('Red con ID duplicado o extremos desconocidos')
        links[ident] = dict(from_node=link.get('from'), to_node=link.get('to'),
            modes=link.get('modes', 'car').split(','),
            length_m=finite(link.get('length'), 'length'), lanes=finite(link.get('permlanes'), 'permlanes'),
            capacity_pcu_per_hour=finite(link.get('capacity'), 'capacity')*3600/period*factor)
    return dict(capacity_period_seconds=period, flow_capacity_factor=factor, links=links,
                semantics='Nominal link PCU/h, already all lanes; not observed flow, signal-adjusted capacity or a network cut.')


def experimental_loads(persons, hourly_probabilities, corridor_links, links, shares=(.7, .5, .3)):
    """Analytical first-origin mixture only: no RNG, population, OD or parameter mutation."""
    if type(persons) is not int or persons < 1:
        raise ValueError('persons debe ser un entero positivo')
    probabilities = [finite(value, 'probabilidad horaria') for value in hourly_probabilities]
    if len(probabilities) != 24 or not math.isclose(math.fsum(probabilities), 1., abs_tol=1e-9):
        raise ValueError('Se requieren 24 probabilidades horarias normalizadas')
    available = {name: sorted(set(ids)) for name, ids in corridor_links.items() if ids}
    seen = set()
    for ids in available.values():
        if seen.intersection(ids) or any(ident not in links or 'car' not in links[ident]['modes'] for ident in ids):
            raise ValueError('Corredores superpuestos o con enlaces car desconocidos')
        seen.update(ids)
    result = []
    for value in shares:
        share = finite(value, 'cuota experimental')
        if share > 1:
            raise ValueError('Cuota experimental fuera de [0,1]')
        corridors = {}
        for name, ids in available.items():
            quota = persons*share/len(available)
            corridors[name] = dict(expected_first_origins=quota,
                expected_hourly_first_origins=[quota*p for p in probabilities],
                link_screening=[dict(link_id=ident, capacity_pcu_per_hour=links[ident]['capacity_pcu_per_hour'],
                    expected_hourly_first_origins=[quota*p/len(ids) for p in probabilities],
                    peak_origin_load_per_nominal_capacity_at_one_pcu=(quota*max(probabilities)/len(ids)/links[ident]['capacity_pcu_per_hour']
                        if links[ident]['capacity_pcu_per_hour'] else None)) for ident in ids])
        result.append(dict(experimental=True, persons=persons, trips_per_person=1, corridor_share=share,
            expected_departures_by_hour=[persons*p for p in probabilities],
            expected_corridor_branch_origins=persons*share if available else None,
            expected_perimeter_branch_origins=persons*(1-share) if available else None,
            corridors=corridors, applicable=bool(available),
            limitations='First-origin branch expectation, not measured entries or throughput. Perimeter can also select corridor links; transit traffic and downstream queues are excluded. Ratios assume one PCU per trip and do not establish feasibility. Proposed weights are not applied to the generator.'))
    return result


def acceptance(report, max_censored_fraction=None):
    """Proposed screening gates, explicitly distinct from empirical validation."""
    if max_censored_fraction is not None:
        max_censored_fraction = finite(max_censored_fraction, 'max_censored_fraction')
        if max_censored_fraction > 1:
            raise ValueError('max_censored_fraction fuera de [0,1]')
    observed = report.get('event_audit')
    gates = dict(normal_24h_configuration=report['horizon'] == dict(start_seconds=0, end_seconds=86400),
                 event_integrity=None, no_native_interventions=None, no_thread_deadlocks_observed=None,
                 no_early_aborts=None, censoring_within_declared_limit=None)
    if observed is not None:
        gates['event_integrity'] = observed['status'] == 'ok'
        native = observed.get('native', {})
        if native.get('decisions', 0):
            gates['no_native_interventions'] = native.get('forced_storage_moves', 0) + native.get('storage_stuck_removals', 0) == 0
        progress = observed.get('progress', {})
        if progress.get('available'):
            gates['no_thread_deadlocks_observed'] = progress.get('max_thread_deadlocks') == 0
        trips = observed.get('trips', {})
        if 'aborted_before_horizon' in trips:
            gates['no_early_aborts'] = trips['aborted_before_horizon'] == 0
        planned = report.get('planned', {}).get('planned_trips')
        if planned and max_censored_fraction is not None:
            unstarted = planned-trips['departures']
            gates['censoring_within_declared_limit'] = unstarted >= 0 and (
                trips['pending_at_horizon']+unstarted)/planned <= max_censored_fraction
    return dict(gates=gates, status='reject' if False in gates.values() else
                'incomplete' if None in gates.values() else 'screening_pass',
                max_censored_fraction=max_censored_fraction, empirical_calibration=False,
                note='Screening pass is not realism or capacity calibration. Queue recurrence, occupied links and waits require interpretation; no silent tolerance for invalid moves or forced storage moves.')


def collect_diagnostics(run_dir, iteration=None, *, inspect_events=False, experiment_persons=(150000, 200000),
                        corridor_shares=(.7, .5, .3), max_censored_fraction=None):
    directory = Path(run_dir).resolve()
    manifest = load_manifest(directory)
    selected = manifest['iterations']['last'] if iteration is None else iteration
    counts = manifest['counts']
    if type(counts.get('planned_persons')) is not int or counts['planned_persons'] < 1:
        raise ValueError('Manifiesto sin conteo valido de personas')
    # The explicit guard runs BEFORE opening/hashing plans or events, including on historical fixtures.
    if inspect_events and counts['planned_persons'] > 1000:
        raise ValueError('--events se limita a pruebas de hasta 1000 personas; no reprocesa la corrida masiva')
    if type(selected) is not int or not manifest['iterations']['first'] <= selected <= manifest['iterations']['last']:
        raise ValueError('Iteracion fuera del intervalo registrado de la corrida')
    if manifest['status'] not in ('prepared', 'completed'):
        raise ValueError('Se requiere una corrida prepared o completed identificable')
    if manifest['status'] == 'completed' and manifest['validation']['status'] != 'valid':
        raise ValueError('La corrida completada no tiene validacion previa valida')
    if manifest['status'] == 'completed' and str(selected) not in manifest['results']:
        raise ValueError('Iteracion sin resultados registrados')
    source = manifest['results'].get(str(selected), {})
    config_record = manifest.get('effective_config', manifest['inputs']['config'])
    config = parameters(checked_path(directory, config_record))
    network_record = source.get('network', manifest['inputs']['network'])
    network = read_network(checked_path(directory, network_record), config.get('qsim.flowCapacityFactor'))
    horizon = dict(start_seconds=seconds(config['qsim.startTime']), end_seconds=seconds(config['qsim.endTime']))
    if horizon != manifest['time_horizon']:
        raise ValueError('Horizonte de configuracion/manifiesto incompatible')
    demand = json.loads(checked_path(directory, manifest['inputs']['demand_report']).read_text(encoding='utf-8'))
    verified = demand.get('xml_verified_counts', {})
    if (demand.get('demand_seed') != manifest['demand_seed'] or verified.get('persons') != counts['planned_persons'] or
            verified.get('trips') != counts['planned_trips'] or demand.get('plans_sha256') != manifest['inputs']['plans']['sha256']):
        raise ValueError('Reporte de demanda incompatible con semilla, conteos o hash de planes del manifiesto')
    temporal = manifest.get('temporal_demand', {})
    histogram = demand.get('departures_by_hour', {})
    if set(histogram) != {f'{hour:02}:00' for hour in range(24)} or any(type(v) is not int or v < 0 for v in histogram.values()):
        raise ValueError('Histograma debe contener 24 horas y conteos enteros no negativos')
    if sum(histogram.values()) != counts['planned_trips']:
        raise ValueError('Histograma horario no concuerda con viajes planificados')
    from simz1_gateway_od import validated_spatial_demand
    spatial = validated_spatial_demand(directory, manifest)
    native = source.get('native_qsim', {})
    report = dict(schema_version=1, run_id=manifest['run_id'], iteration=selected,
        manifest_sha256=sha256(directory/MANIFEST), horizon=horizon,
        observed_event_end_seconds=source.get('observed_event_end_seconds'),
        demand_window=manifest.get('demand_window'), planned=counts,
        planned_departures_by_hour=histogram, seeds=dict(demand=manifest['demand_seed'], matsim=manifest['matsim_seed']),
        effective_settings={key: config.get(key) for key in (
            'qsim.flowCapacityFactor', 'qsim.storageCapacityFactor', 'qsim.useLanes',
            'qsim.stuckTime', 'qsim.removeStuckVehicles', 'qsim.simEndtimeInterpretation',
            'signalsystems.useSignalsystems', 'zona1Priority.enabled',
            'simz1Admission.storagePolicy',
            'zona1Diagnostics.incidentsEnabled', 'zona1WithinDayRouting.enabled')},
        provenance=dict(checked_small_artifacts=['config', 'network', 'demand_report'],
            plans_and_events_revalidated=False, source_counts='Previously recorded manifest; not recomputed at 24 h.'),
        recorded_source_metrics=dict(counts=source.get('counts'), native=native,
            scope='Full recorded event file; configured horizon and observed last event are retained separately. Not a 24 h crop.'),
        concentration=dict(corridor_policy=demand.get('corridor_policy'), corridor_share=demand.get('corridor_share'),
            origins_by_source=demand.get('origins_by_source'), physical_origins_by_corridor=demand.get('physical_origins_by_corridor'),
            missing_corridors=demand.get('missing_corridors'),
            gateway_entry_links=spatial.get('entry_gateways') if spatial else None,
            gateway_exit_links=spatial.get('exit_gateways') if spatial else None,
            gateway_realized_od_counts=spatial.get('realized_counts') if spatial else None),
        entry_capacity=dict(status='unavailable', observed_boundary_entry_flow=None,
            reason='Network origins/perimeter are not administrative gateway crossings. No verified entry cut or boundary throughput is inferred.'),
        network=network, experiments=[], temporal_experiments=[], event_audit=None, link_capacity_screening=None,
        limitations=[
            '150k-200k are synthetic persons, not traffic counts or unique boundary entries.',
            'WAIT counts are decision attempts, not seconds, queue length or unique vehicles.',
            'Link vehicle occupancy is not native lane storage/PCU utilization. Detailed lanes and effective vehicle PCU require native storage telemetry.',
            'Thread deadlock evidence differs from traffic saturation. Slow wall-clock processing or no observed crossing alone does not establish simulation stalling.',
            'No speeds, capacity, demand distribution, population or native events are changed.'])
    probabilities = temporal.get('hourly_probabilities')
    if probabilities is not None and not spatial:
        for people in experiment_persons:
            report['experiments'].extend(experimental_loads(people, probabilities, demand.get('corridor_links', {}),
                                                           network['links'], corridor_shares))
            for label, distribution in (('current_synthetic', probabilities), ('uniform_experimental', [1/24]*24),
                    ('half_current_half_uniform_experimental', [p/2+1/48 for p in probabilities])):
                report['temporal_experiments'].append(dict(persons=people, profile=label, experimental=True,
                    expected_departures_by_hour=[people*p for p in distribution],
                    peak_expected_departures_per_hour=people*max(distribution), applied=False))
    if spatial:
        report['entry_capacity']['reason'] = ('Gateway catalog is recorded, but boundary flow is not measured by interior activity starts. '
            'Use per-link native throughput and verify a directed entry cut before summing capacities; reachable OD weighting remains experimental.')
        report['entry_capacity']['gateway_nominal_pcu_per_hour'] = {
            ident: network['links'][ident]['capacity_pcu_per_hour'] for ident in spatial['entry_gateways']
            if ident in network['links'] and 'car' in network['links'][ident]['modes']}
    if inspect_events:
        if manifest['status'] != 'completed' or horizon != dict(start_seconds=0, end_seconds=86400):
            raise ValueError('--events requiere una corrida pequena completed/valid de 0..86400; no recorta el historico')
        from simz1_capacity_events import CapacityEventAudit
        from simz1_event_validation import enabled_lane_movements
        lane_moves = None
        if config.get('qsim.useLanes') == 'true':
            lane_records = manifest.get('effective_lane_configuration_validation', {}).get('loaded_artifacts', {})
            lane_record = lane_records.get('lanes') or manifest['inputs'].get('input:network-laneDefinitionsFile.xml')
            if lane_record is None:
                raise ValueError('Carriles efectivos sin artefacto validado')
            lane_path = checked_path(directory, lane_record)
            lane_opener = gzip.open if str(lane_path).endswith('.gz') else open
            with lane_opener(lane_path, 'rb') as lane_stream:
                lane_moves = enabled_lane_movements(lane_stream)
        links = {ident:(link['from_node'], link['to_node'], set(link['modes'])) for ident, link in network['links'].items()}
        audit = CapacityEventAudit(links, lane_moves,
            corridor_links={name: ids for name, ids in demand.get('corridor_links', {}).items() if ids})
        event_path = checked_path(directory, source['events'])
        opener = gzip.open if str(event_path).endswith('.gz') else open
        with opener(event_path, 'rb') as stream:
            context = ET.iterparse(stream, events=('start', 'end'))
            _, root = next(context)
            if root.tag != 'events':
                raise ValueError('Raiz de eventos invalida')
            for action, event in context:
                if action == 'end' and event.tag == 'event':
                    audit.consume(event)
                    event.clear(); root.clear()
        report['event_audit'] = audit.summary()
        report['link_capacity_screening'] = {ident: dict(
            nominal_capacity_pcu_per_hour=network['links'][ident]['capacity_pcu_per_hour'],
            observed_exits_vehicles_by_hour=row['exits_by_hour'],
            peak_exits_per_nominal_capacity_assuming_one_pcu=(max(row['exits_by_hour'])/network['links'][ident]['capacity_pcu_per_hour']
                if network['links'][ident]['capacity_pcu_per_hour'] else None),
            limitation='Screening only: observed vehicles versus nominal PCU, assuming one PCU each; not signal-adjusted capacity.')
            for ident, row in report['event_audit']['link_metrics'].items() if row['max_occupancy_vehicles']}
        if spatial:
            report['entry_capacity']['observed_gateway_proxy_metrics'] = {
                ident: dict(origin_injections=report['event_audit']['link_metrics'][ident]['network_entries'],
                    link_exits_by_hour=report['event_audit']['link_metrics'][ident]['exits_by_hour'])
                for ident in spatial['entry_gateways']}
        trips = report['event_audit']['trips']
        report['plan_reconciliation'] = dict(planned_trips=counts['planned_trips'],
            departed_by_horizon=trips['departures'], not_started_by_horizon=counts['planned_trips']-trips['departures'],
            pending_departed_at_horizon=trips['pending_at_horizon'],
            note='Not-started planned trips are separate from censored departed trips and active network vehicles.')
        if report['plan_reconciliation']['not_started_by_horizon'] < 0:
            raise ValueError('Salidas exceden viajes planificados; revisar identidad de planes/eventos')
        report['provenance']['events_revalidated'] = True
    report['acceptance'] = acceptance(report, max_censored_fraction)
    return report


def brief(report):
    source = report['recorded_source_metrics']
    native = source['native']
    rows = [f"SimZ1 {report['run_id']} / iteracion {report['iteration']}",
        f"Horizonte configurado: {report['horizon']}; ultimo evento fuente: {report['observed_event_end_seconds']}",
        f"Personas/viajes planificados: {report['planned']['planned_persons']}/{report['planned']['planned_trips']}",
        f"Pico planificado por hora: {max(report['planned_departures_by_hour'].items(), key=lambda item:item[1])}",
        f"Intervenciones registradas (archivo completo): forzados={native.get('forced_storage_moves', 'N/D')}, retiros={native.get('storage_stuck_removals', 'N/D')}",
        f"Origenes fisicos por corredor: {report['concentration']['physical_origins_by_corridor']}",
        'Caudal administrativo de entrada a Z1: N/D; origenes de planes no equivalen a cruces del limite.']
    for experiment in report['experiments']:
        rows.append(f"EXPERIMENTAL N={experiment['persons']}, cuota={experiment['corridor_share']:.0%}: "
                    f"origenes rama corredor={experiment['expected_corridor_branch_origins']}, "
                    f"perimetro={experiment['expected_perimeter_branch_origins']}; no aplicado.")
    if report['event_audit'] is not None:
        audit = report['event_audit']
        rows.extend([f"Viajes al corte estricto 86400: {audit['trips']}",
            f"Ocupacion activa car al corte: {audit['active_car_vehicles_at_horizon']}; no es el numero de pendientes.",
            f"WAIT por categoria (intentos): {audit['native']['wait_attempts_by_category']}",
            f"Recurrencia maxima observada de WAIT: {audit['persistent_wait']['max_observed_span_seconds']} s; no es espera continua.",
            f"Transiciones/decisiones invalidas: {audit['validation']['counts']}"])
    rows.extend([f"Aceptacion propuesta: {report['acceptance']['status']} {report['acceptance']['gates']}",
                 'Sin calibracion empirica. WAIT=intentos; recurrencia no prueba espera continua; 24:00 es cierre, no hora 25.',
                 'Ocupacion/colas/caudal nuevos requieren --events en corrida pequena completada, nunca sobre el fixture 100k.'])
    return '\n'.join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--iteration', type=int)
    parser.add_argument('--events', action='store_true', help='Auditoria explicita de eventos: solo <=1000 personas, completed/valid y 24h')
    parser.add_argument('--experiment-persons', type=int, nargs='+', default=[150000, 200000])
    parser.add_argument('--corridor-shares', type=float, nargs='+', default=[.7, .5, .3])
    parser.add_argument('--max-censored-fraction', type=float, help='Umbral experimental explicito [0,1]; omitir deja el criterio pendiente')
    parser.add_argument('--output', type=Path, help='JSON nuevo opcional; no sobrescribe archivos ni crea carpetas')
    args = parser.parse_args()
    try:
        report = collect_diagnostics(args.run_dir, args.iteration, inspect_events=args.events,
            experiment_persons=args.experiment_persons, corridor_shares=args.corridor_shares,
            max_censored_fraction=args.max_censored_fraction)
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
        print(brief(report))
        if report['event_audit'] is not None and report['acceptance']['status'] == 'reject':
            parser.exit(2, 'Detenerse: fallaron criterios de integridad/intervenciones/censura; conservar evidencia.\n')
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        parser.exit(1, f'No se pudo diagnosticar: {error}\n')


if __name__ == '__main__':
    main()
