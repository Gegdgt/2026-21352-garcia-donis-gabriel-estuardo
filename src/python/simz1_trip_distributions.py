"""A bounded set of distribution views; no scores or per-person PNG fan-out."""
from array import array
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from simz1_trip_table import rows, inventory, iteration_selection, export_table, DEFINITION


def duration_statistics(values):
    """One exact statistic implementation for existing and thesis views, in seconds."""
    data = np.frombuffer(values, dtype='float64')
    quantiles = np.quantile(data, [.05, .25, .50, .75, .95]) if len(data) else [None] * 5
    return dict(mean_seconds=float(data.mean()) if len(data) else None,
                **{key: float(value) if value is not None else None for key, value in
                   zip(('p05_seconds', 'p25_seconds', 'p50_seconds', 'p75_seconds', 'p95_seconds'), quantiles)})


def write_csv(path, records, fields):
    with Path(path).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(records)


def distributions(path, mode='car'):
    counts=Counter();groups=defaultdict(lambda:dict(statuses=Counter(),values=array('d')))
    values=array('d')
    for row in rows(path):
        counts['total']+=1
        if mode!='all' and row['mode']!=mode:
            counts['other_mode']+=1;continue
        counts['selected_mode']+=1;counts[row['status']]+=1
        hour=int(row['departure']//3600)
        keys=(('profile',row['profile'],None),('hour',None,hour),('profile_hour',row['profile'],hour))
        for key in keys:
            groups[key]['statuses'][row['status']]+=1
        if row['status']=='completed':
            values.append(row['duration_seconds'])
            for key in keys:groups[key]['values'].append(row['duration_seconds'])
    summaries=[]
    for (view,profile,hour),group in sorted(groups.items(),key=lambda kv:str(kv[0])):
        states=group['statuses'];complete=states['completed'];total=sum(states.values())
        summaries.append(dict(view=view,mode=mode,profile=profile,hour=hour,n_total=total,n_complete=complete,
            n_excluded=total-complete,n_aborted=states['aborted'],n_censored=states['censored'],
            completion_rate=complete/total,**duration_statistics(group['values'])))
    report=dict(mode_filter=mode,n_total=counts['total'],n_complete=counts['completed'],
        n_excluded=counts['total']-counts['completed'],n_other_mode=counts['other_mode'],
        n_aborted=counts['aborted'],n_censored=counts['censored'],n_selected_mode=counts['selected_mode'],
        completion_rate=counts['completed']/counts['selected_mode'] if counts['selected_mode'] else None,
        summary_exclusions='Group n_excluded counts aborted/censored in selected modes; other modes excluded before grouping.',
        definition=DEFINITION)
    return values,groups,summaries,report


def plot_distributions(path, destination, identity, mode='car'):
    from simz1_run import atomic_json
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    values,groups,summaries,report=distributions(path,mode)
    caption=f"N completos={report['n_complete']}; excluidos={report['n_excluded']} (otro modo={report['n_other_mode']})"
    data=np.sort(np.frombuffer(values,dtype='float64'))
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    if len(data):
        axes[0].hist(data,bins=min(50,max(1,int(np.sqrt(len(data))))),color='#087eaa',edgecolor='white')
        axes[1].step(np.r_[data[0],data],np.r_[0,np.arange(1,len(data)+1)/len(data)],where='post',color='#087eaa')
    else:
        for ax in axes:ax.text(.5,.5,'Sin viajes completos del modo seleccionado',transform=ax.transAxes,ha='center')
    axes[0].set(xlabel='Duracion de etapa completada (s)',ylabel='Numero de etapas',title='Histograma')
    axes[1].set(xlabel='Duracion de etapa completada (s)',ylabel='Fraccion acumulada',ylim=(0,1.03),title='ECDF')
    fig.suptitle(identity+f' | modo={mode}\n'+caption);fig.tight_layout()
    fig.savefig(destination/'duration_distribution.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,6))
    profiles=sorted((key for key in groups if key[0]=='profile'),key=str)
    if profiles:
        boxes=[]
        for key in profiles:
            g=groups[key];n=g['statuses']['completed'];excluded=sum(g['statuses'].values())-n
            quantiles=np.quantile(g['values'],[.05,.25,.50,.75,.95]) if n else [np.nan]*5
            boxes.append(dict(label=f'{key[1]}\nN={n}; excl={excluded}',
                              **dict(zip(('whislo','q1','med','q3','whishi'),quantiles))))
        axes[0].bxp(boxes,showfliers=False)
    else:axes[0].text(.5,.5,'Sin completos',transform=axes[0].transAxes,ha='center')
    hourly=sorted((r for r in summaries if r['view']=='hour'),key=lambda r:r['hour'])
    x=[r['hour'] for r in hourly];median=[np.nan if r['p50_seconds'] is None else r['p50_seconds'] for r in hourly]
    low=[np.nan if r['p05_seconds'] is None else r['p05_seconds'] for r in hourly]
    high=[np.nan if r['p95_seconds'] is None else r['p95_seconds'] for r in hourly]
    axes[1].plot(x,median,'o-',label='p50');axes[1].fill_between(x,low,high,alpha=.25,label='p05-p95')
    axes[1].set_xticks(x,[f"{r['hour']}\n{r['n_complete']}/{r['n_excluded']}" for r in hourly],fontsize=8)
    axes[1].legend();axes[1].grid(alpha=.2)
    axes[0].set(ylabel='Duracion completada (s)',title='Perfiles: caja p25-p75; bigotes p05-p95')
    axes[1].set(xlabel='Hora absoluta de salida\nN completos / excluidos del modo',ylabel='Duracion completada (s)',title='Distribucion por hora')
    fig.suptitle(identity+f' | modo={mode}\n'+caption);fig.tight_layout()
    fig.savefig(destination/'profile_hour_distribution.png',dpi=160);plt.close(fig)
    fields=['view','mode','profile','hour','n_total','n_complete','n_excluded','n_aborted','n_censored','completion_rate',
            'mean_seconds','p05_seconds','p25_seconds','p50_seconds','p75_seconds','p95_seconds']
    write_csv(destination/'percentiles_profile_hour.csv',summaries,fields)
    report['identity']=identity
    atomic_json(destination/'distribution_summary.json',report)
    return report


PROFILE_ORDER = ('Normal', 'Tortuga', 'Liebre', 'Motociclista', 'MotocicletaLenta', 'MotocicletaRapida')
PROFILE_LABELS = ('Carro (Normal)', 'Carro Tortuga (Tortuga)', 'Carro liebre (Liebre)',
                  'Moto', 'Moto tortuga', 'Moto Liebre')
PROFILE_INFO = {key: (label, 'Carro' if index < 3 else 'Moto')
                for index, (key, label) in enumerate(zip(PROFILE_ORDER, PROFILE_LABELS))}
PROFILE_METRIC = ('Duracion de viaje/etapa completada = (PersonArrivalEvent.time - '
                  'PersonDepartureEvent.time) / 60, en minutos simulados. Hora de SALIDA '
                  'absoluta: [h:00, (h+1):00), h=00..23. Llegadas posteriores a 24:00 '
                  'se incluyen si su salida pertenece a la jornada. Cada fila canonica '
                  'es una etapa departure-arrival; no un segmento ni un viaje multimodal puerta a puerta.')
CONTINUOUS_PROFILE_METRIC = ('Duracion completada = (PersonArrivalEvent.time - PersonDepartureEvent.time) / 60, '
    'en minutos absolutos simulados. Solo cohorte principal; hora 00..23 atribuida a la salida PLANIFICADA '
    'inmutable relativa al inicio de la jornada. Salida observada o llegada posterior a medianoche se '
    'conserva en esa cohorte. Contexto de calentamiento/extension se informa por separado. Sin modulo '
    'en eventos, claves ni duraciones; censurados no tienen duracion imputada.')


def _profile_group():
    return dict(statuses=Counter(), values=array('d'), modes=set())


def _observe_profile(group, row):
    group['statuses'][row['status']] += 1
    group['modes'].add(row['mode'])
    if row['status'] == 'completed':
        group['values'].append(row['duration_seconds'])


def _profile_summary(group, run_id, iteration, min_sample, *, profile=None, family=None, hour=None, label=None):
    states = group['statuses']
    total, complete = sum(states.values()), states['completed']
    stats = duration_statistics(group['values'])
    return dict(run_id=run_id, iteration=iteration, profile=profile, label=label or profile or family,
                family=family, hour=hour, hour_start=f'{hour:02}:00' if hour is not None else None,
                hour_end=f'{hour:02}:59' if hour is not None else None,
                modes=sorted(group['modes']), n_total=total, n_complete=complete,
                n_excluded=total-complete, n_aborted=states['aborted'], n_censored=states['censored'],
                completion_rate=complete/total if total else None,
                aborted_rate=states['aborted']/total if total else None,
                censored_rate=states['censored']/total if total else None,
                excluded_rate=(total-complete)/total if total else None,
                mean_minutes=stats['mean_seconds']/60 if complete else None,
                median_minutes=stats['p50_seconds']/60 if complete else None,
                p95_minutes=stats['p95_seconds']/60 if complete else None,
                sample_status=('sin datos' if not total else 'sin completos' if not complete else
                               'muestra pequeña' if complete < min_sample else 'ok'))


def profile_statistics(path, metadata, run_id, iteration, min_sample=30, temporal_policy=None):
    """Read canonical rows once; pool individual durations, never group averages.

    Only numeric durations are retained for exact percentiles (no DataFrame or
    event/segment replay). Identity metadata comes from the validated scenario.
    The threshold is a descriptive flag, not a test of statistical significance.
    """
    if type(min_sample) is not int or min_sample < 1:
        raise ValueError('min_sample debe ser un entero positivo')
    groups = defaultdict(_profile_group)
    counts = Counter(dict(total_rows=0, selected_rows=0, outside_departure_window=0,
                          unclassified_rows=0, separate_rows=0, completed=0, aborted=0, censored=0))
    all_complete = array('d')
    study = temporal_policy.get('windows', {}).get('study') if temporal_policy else None
    if study and study['end_seconds'] - study['start_seconds'] != 86400:
        raise ValueError('La cohorte principal requiere una jornada completa de 86400 segundos')
    for row in rows(path):
        if row['run_id'] != run_id or row['iteration'] != iteration:
            raise ValueError('CSV de otra corrida/iteracion')
        counts['total_rows'] += 1
        person = metadata.get(row['person_id'], {})
        if study:
            if person.get('population_cohort') != 'main':
                counts['auxiliary_context_rows'] += 1
                continue
            planned = person.get('planned_departure_seconds')
            if planned is None or not study['start_seconds'] <= planned < study['end_seconds']:
                raise ValueError('Persona principal fuera de su ventana planificada')
            hour = int((planned - study['start_seconds']) // 3600)
            counts['observed_departures_after_study'] += row['departure'] >= study['end_seconds']
        else:
            hour = int(row['departure'] // 3600)
        if not 0 <= hour < 24:
            counts['outside_departure_window'] += 1
            continue
        kind = person.get('effective_vehicle_type') or person.get('profile')
        family = person.get('family', 'unknown')
        eligible = person.get('monte_carlo_eligible', False)
        expected_family = PROFILE_INFO.get(kind, (None, None))[1]
        coherent = (expected_family is not None and
                    family.lower() == ('carro' if expected_family == 'Carro' else 'moto'))
        if not coherent or not eligible:
            counts['separate_rows'] += 1
            if family in ('unknown', None) or not person:
                category = 'sin identidad efectiva'
                counts['unclassified_rows'] += 1
            elif not eligible:
                category = 'fuera de poblacion Monte Carlo: ' + str(kind or family)
            else:
                category = str(kind or family)
            _observe_profile(groups[('separate', category, family, None)], row)
            _observe_profile(groups[('separate_hour', category, family, hour)], row)
            continue
        counts['selected_rows'] += 1
        counts[row['status']] += 1
        for key in (('profile', kind, expected_family, None), ('profile_hour', kind, expected_family, hour),
                    ('family', None, expected_family, None), ('family_hour', None, expected_family, hour)):
            _observe_profile(groups[key], row)
        if row['status'] == 'completed':
            all_complete.append(row['duration_seconds'])

    def summary(view, profile, family, hour, label=None):
        return _profile_summary(groups[(view, profile, family, hour)], run_id, iteration, min_sample,
                                profile=profile, family=family, hour=hour, label=label)

    profiles = [summary('profile', key, PROFILE_INFO[key][1], None, PROFILE_INFO[key][0]) for key in PROFILE_ORDER]
    profile_hour = [summary('profile_hour', key, PROFILE_INFO[key][1], hour, PROFILE_INFO[key][0])
                    for key in PROFILE_ORDER for hour in range(24)]
    families = [summary('family', None, family, None) for family in ('Carro', 'Moto')]
    family_hour = [summary('family_hour', None, family, hour) for family in ('Carro', 'Moto') for hour in range(24)]
    separate = [summary(view, key, family, hour) for view, key, family, hour in sorted(groups, key=str)
                if view == 'separate']
    separate_hour = [summary(view, key, family, hour) for view, key, family, hour in sorted(groups, key=str)
                     if view == 'separate_hour']
    dist = duration_statistics(all_complete)
    distribution = dict(n_complete=len(all_complete),
                        mean_minutes=dist['mean_seconds']/60 if all_complete else None,
                        median_minutes=dist['p50_seconds']/60 if all_complete else None,
                        values_minutes=array('d', (value/60 for value in all_complete)),
                        **{key.replace('_seconds', '_minutes'): value/60 if value is not None else None
                           for key, value in dist.items() if key.startswith('p')})
    return dict(schema_version=1, run_id=run_id, iteration=iteration, min_sample=min_sample,
                metric_definition=CONTINUOUS_PROFILE_METRIC if study else PROFILE_METRIC, canonical_definition=DEFINITION,
                filters=dict(departure_seconds=(f"main cohort by immutable planned departure in [{study['start_seconds']}, {study['end_seconds']}); actual departures/arrivals outside study retained; no modulo" if study else '0 <= departure < 86400; no modulo 24'),
                             cohort_hour_basis='planned departure relative to study start' if study else 'observed PersonDepartureEvent absolute hour',
                             duration_status='completed only; aborted/censored excluded from durations',
                             modes='all observed MATSim modes; listed per group, not inferred from vehicle speed',
                             identities='effective scenario type/family; six road profiles; other categories separate',
                             exclusion_denominator='n_total of the same departure cohort; n_excluded = aborted + censored'),
                weighting='Each completed canonical row has weight 1, including repeated trips by one person; family/global percentiles use pooled individual durations.',
                quantiles='numpy.quantile, linear interpolation, exact observations',
                identity_fields=dict(person_id='Demand person key; never inferred from vehicle_id',
                    vehicle_id='First observed vehicle; vehicle_ids preserves all vehicles in the canonical row',
                    trip_index='1-based departure ordinal per person and iteration, across all modes',
                    profile='Recorded effective vehicle type, with explicit historical Normal/Tortuga/Liebre mapping',
                    family='Carro/Moto from effective scenario identity; heavy, passengers and unknown/internal drivers separate',
                    mode='Actual PersonDepartureEvent legMode, retained in each canonical row; distinct from family/profile'),
                missing_data='null in JSON and sin datos in CSV; no duration is imputed as zero',
                sample_note=f'N completos < {min_sample} is flagged descriptively; no significance claim.',
                counts=dict(counts), profiles=profiles, profile_hour=profile_hour,
                families=families, family_hour=family_hour, separate_categories=separate,
                separate_categories_hour=separate_hour,
                distribution=distribution)


def plot_profile_analysis(path, destination, run_id, iteration, metadata, *, min_sample=30, provenance=None, temporal_policy=None):
    """Publish a bounded thesis deliverable into a new directory, preserving old plots."""
    from simz1_run import atomic_json
    from simz1_profile_plots import render_profile_plots
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f'No se sobrescriben graficas existentes: {destination}; use otro --analysis-dir')
    report = profile_statistics(path, metadata, run_id, iteration, min_sample, temporal_policy)
    if temporal_policy:
        report['temporal_policy'] = temporal_policy
    report['provenance'] = provenance or {}
    from simz1_result_quality import assess
    report['result_quality'] = assess(report)
    data = np.frombuffer(report['distribution'].pop('values_minutes'), dtype='float64')
    destination.mkdir(parents=True, exist_ok=True)
    atomic_json(destination/'calidad_resultados.json', report['result_quality'])
    render_profile_plots(report, destination)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    dist = report['distribution']
    if len(data):
        axes[0].hist(data, bins=min(50, max(1, int(np.sqrt(len(data))))), color='#087eaa', edgecolor='white')
        for key, label, color in (('median_minutes', 'Mediana', '#b34a00'), ('p95_minutes', 'P95', '#7828a0')):
            axes[0].axvline(dist[key], label=f'{label} = {dist[key]:.2f} min', color=color, linestyle='--')
        axes[0].legend()
        ordered = np.sort(data)
        axes[1].step(np.r_[ordered[0], ordered], np.r_[0, np.arange(1, len(data)+1)/len(data)], where='post')
    else:
        for ax in axes:
            ax.text(.5, .5, 'Sin datos de viajes completados', transform=ax.transAxes, ha='center')
    axes[0].set(xlabel='Duración del viaje completado (minutos simulados)', ylabel='Viajes completados', title='Histograma de observaciones individuales')
    axes[0].yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    axes[1].set(xlabel='Duración del viaje completado (minutos simulados)', ylabel='Fracción acumulada', title='Distribución acumulada', ylim=(0, 1.03))
    cohort_label = 'cohorte principal planificada 00:00–23:59' if temporal_policy else 'salida observada 00:00–23:59'
    fig.suptitle(f'SimZ1 {run_id} | iteración {iteration}\nSeis perfiles; {cohort_label}; todos los modos registrados; N completos={len(data)}')
    fig.tight_layout()
    fig.savefig(destination/'duration_distribution.png', dpi=180,
                metadata=dict(Description=json.dumps({key: report[key] for key in ('run_id', 'iteration', 'metric_definition', 'filters')}, ensure_ascii=False)))
    plt.close(fig)
    fields = list(report['profile_hour'][0]) + ['metric_definition', 'filters']
    for name, records in (('estadisticas_por_perfil_hora.csv', report['profile_hour']),
                          ('estadisticas_por_familia_hora.csv', report['family_hour']),
                          ('estadisticas_globales.csv', report['profiles'] + report['families']),
                          ('categorias_separadas.csv', report['separate_categories']),
                          ('categorias_separadas_por_hora.csv', report['separate_categories_hour'])):
        def formatted():
            for record in records:
                values = {key: ('sin datos' if value is None else value) for key, value in record.items()}
                values['modes'] = '|'.join(record['modes']) or 'sin datos'
                values.update(metric_definition=report['metric_definition'], filters=json.dumps(report['filters'], ensure_ascii=False))
                yield values
        write_csv(destination/name, formatted(), fields)
    atomic_json(destination/'resumen_perfiles.json', report)
    return report


def follow_person(selection, person, trip_index, destination, mode='car', exported=None):
    if trip_index<1:raise ValueError('--trip-index debe ser positivo')
    from simz1_run import atomic_json
    exported={} if exported is None else exported
    history=[]
    for item in inventory(selection):
        iteration=item['iteration']
        if iteration>selection['iteration']:continue
        record=dict(run_id=selection['manifest']['run_id'],iteration=iteration,person_id=person,trip_index=trip_index,
                    vehicle_id=None,mode=None,profile=None,departure=None,arrival=None,duration_seconds=None,
                    status='missing_iteration_data' if item['source'] is None else 'no_departure',included=False,
                    departure_link=None,arrival_link=None)
        if item['source']:
            if iteration not in exported:exported[iteration]=export_table(iteration_selection(selection,iteration))[0]
            for row in rows(exported[iteration]):
                if row['person_id']==person and row['trip_index']==trip_index:
                    record.update({k:row[k] for k in record if k in row})
                    record['included']=row['status']=='completed' and (mode=='all' or row['mode']==mode)
        history.append(record)
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    fields=['run_id','iteration','person_id','vehicle_id','trip_index','mode','profile','departure','arrival','duration_seconds',
            'status','included','departure_link','arrival_link']
    write_csv(destination/'individual_evolution.csv',history,fields)
    complete=sum(r['included'] for r in history);excluded=len(history)-complete
    signatures={(r['mode'],r['departure_link'],r['arrival_link']) for r in history if r['status']=='completed'}
    comparable=len(signatures)<=1
    fig,ax=plt.subplots(figsize=(10,5))
    # NaNs split the line at censored, absent and excluded observations.
    ax.plot([r['iteration'] for r in history],[r['duration_seconds'] if r['included'] else np.nan for r in history],'o-')
    ax.set(xlabel='Iteracion',ylabel='Duracion de etapa completada (s)',title=
        f"{selection['manifest']['run_id']}\nPersona {person}; etapa ordinal {trip_index}; modo={mode}\nN completos={complete}; excluidos/ausentes={excluded}")
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True));ax.grid(alpha=.2)
    if not comparable:fig.text(.5,.01,'Cambio de modo u origen/destino: el mismo ordinal no acredita un itinerario comparable.',ha='center',fontsize=8)
    if not complete:ax.text(.5,.5,'Sin duraciones completas para esta seleccion',transform=ax.transAxes,ha='center')
    fig.tight_layout(rect=(0,.04,1,1));fig.savefig(destination/'individual_evolution.png',dpi=160);plt.close(fig)
    report=dict(person_id=person,trip_index=trip_index,mode_filter=mode,n_complete=complete,n_excluded=excluded,
                statuses=dict(Counter(r['status'] for r in history)),same_completed_mode_and_endpoints=comparable,
                matching='Observed departure ordinal within person/iteration, not guaranteed persistent OD identity',
                missing_iterations=[r['iteration'] for r in history if r['status']=='missing_iteration_data'])
    atomic_json(destination/'individual_summary.json',report)
    return report
