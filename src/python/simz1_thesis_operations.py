"""Presentation of verified SimZ1 summaries, without reading events or replay.

The caller owns identity/hash verification and publication. Missing measurements
remain null; only sparse fixed-day Counter fields have a schema-defined zero.
"""
from collections import defaultdict
import math


COLORS = {'planned': '#64748b', 'departure': '#0072b2', 'entry': '#009e73',
          'arrival': '#cc79a7', 'active': '#0072b2', 'pending': '#d55e00',
          'bus': '#8064a2', 'freight': '#b0792a'}


def number(value):
    if value is None or value == '':
        return None
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Non-finite measurement in operational source')
    return value


def numeric_rows(rows):
    """Keep text fields, convert actual numerics, reject non-finite numbers."""
    result = []
    for row in rows:
        clean = {}
        for key, value in row.items():
            if value is None or value == '':
                clean[key] = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                clean[key] = number(value)
            elif isinstance(value, str):
                try:
                    clean[key] = number(value)
                except ValueError:
                    if value.lower() in ('nan', 'inf', '-inf', 'infinity', '-infinity'):
                        raise
                    clean[key] = value
            else:
                clean[key] = value
        result.append(clean)
    return result


def _sum_known(rows, key):
    values = [number(r.get(key)) for r in rows]
    return sum(values) if all(v is not None for v in values) else None


def aggregate_temporal(rows, seconds=3600):
    """Aggregate exact count bins, areas and endpoint gauges, never mean means.

    Counts cannot be split across requested boundaries without raw event times.
    Gaps and missing values remain unavailable. Partial output bins are labelled.
    """
    if seconds <= 0 or not math.isfinite(seconds):
        raise ValueError('Positive finite aggregation interval required')
    rows = numeric_rows(rows)
    bins = defaultdict(list)
    previous_end = None
    for row in rows:
        start, end = number(row.get('start_seconds')), number(row.get('end_seconds'))
        if start is None or end is None or end <= start:
            raise ValueError('Invalid source interval')
        if previous_end is not None and start < previous_end:
            raise ValueError('Overlapping or duplicate temporal intervals')
        if int(start // seconds) != int(math.nextafter(end, -math.inf) // seconds):
            raise ValueError('Cannot divide count interval over aggregation boundary')
        if row.get('duration_seconds') is not None and not math.isclose(row['duration_seconds'], end-start):
            raise ValueError('Source interval duration differs from endpoints')
        bins[int(start // seconds)].append(row)
        previous_end = end
    result = []
    controls = {'start_seconds', 'end_seconds', 'duration_seconds', 'final_boundary_inclusive'}
    for bucket, members in sorted(bins.items()):
        first, last = members[0], members[-1]
        span = last['end_seconds'] - first['start_seconds']
        coverage = sum(r['end_seconds'] - r['start_seconds'] for r in members)
        continuous = math.isclose(coverage, span)
        record = dict(start_seconds=first['start_seconds'], end_seconds=last['end_seconds'],
                      duration_seconds=span, observed_seconds=coverage,
                      continuous_coverage=continuous, full_bucket=continuous and math.isclose(span, seconds),
                      source_bins=len(members), final_boundary_inclusive=last.get('final_boundary_inclusive'))
        for key in set().union(*(r.keys() for r in members)) - controls:
            if key.startswith(('active_mean_', 'pending_mean_')):
                continue
            if key.startswith(('active_start_', 'pending_start_')):
                record[key] = first.get(key)
            elif key.startswith(('active_end_', 'pending_end_')):
                record[key] = last.get(key)
            elif all(r.get(key) is None or isinstance(r.get(key), (int, float)) for r in members):
                record[key] = _sum_known(members, key) if continuous else None
        for prefix, area in [('active', 'active_vehicle_seconds'), ('pending', 'pending_person_seconds')]:
            for group in ('main', 'context', 'public'):
                value = record.get(f'{area}_{group}')
                record[f'{prefix}_mean_{group}'] = value/span if value is not None and continuous else None
        result.append(record)
    return result


def _plt():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def _heading(fig, title, bundle, note=''):
    identity = bundle['identity']
    subtitle = f"N configurado = {identity.get('N_configured', '?'):,}" if isinstance(identity.get('N_configured'), (int, float)) else 'N configurado: no disponible'
    subtitle += f"  ·  Iteración {identity['iteration']}"
    if identity.get('publication_status') and 'diagnostic' in identity['publication_status'].lower():
        subtitle += '  ·  DIAGNÓSTICO: prefijo observado'
    fig.suptitle(title, fontsize=16, fontweight='semibold', y=.99)
    fig.text(.5, .925, subtitle, ha='center', fontsize=10, color='#475569')
    if note:
        fig.text(.055, .015, note, fontsize=9, color='#475569', va='bottom')
    fig.tight_layout(rect=(.02, .07 if note else .035, .99, .89))


def _time_axis(ax, bundle, rows=None, x_key='hour'):
    horizon = bundle['identity'].get('horizon_seconds', bundle['identity'].get('horizon'))
    if isinstance(horizon, dict):
        horizon = horizon.get('end_seconds')
    if horizon is None:
        horizon = bundle.get('operational_report', {}).get('horizon', {}).get('end_seconds')
    maximum = max([24, (number(horizon) or 86400)/3600] +
                  [number(r.get(x_key)) or 0 for r in (rows or [])])
    ax.set_xlim(0, maximum)
    step = max(1, math.ceil(maximum/12))
    ticks = list(range(0, math.ceil(maximum)+1, step))
    ax.set_xticks(ticks, [f'{h:02d}:00' for h in ticks])
    ax.set_xlabel('Hora simulada')
    ax.set_ylim(bottom=0)
    if ax.get_ylim()[1] < .1:
        ax.set_ylim(0, 1)
    ax.grid(axis='y', alpha=.22)
    ax.spines[['top', 'right']].set_visible(False)


def _line(ax, rows, field, label, color, x_key='hour', **kwargs):
    values = [number(row.get(field)) for row in rows]
    if any(v is not None for v in values):
        ax.plot([row[x_key] for row in rows], [math.nan if v is None else v for v in values],
                label=label, color=color, linewidth=1.7, **kwargs)
        return True
    return False


def _legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(frameon=True, facecolor='white', framealpha=1, edgecolor='none', fontsize=9, loc='upper left')
    else:
        ax.text(.5, .5, 'Medición no disponible', transform=ax.transAxes, ha='center', color='#64748b')


def _metadata(title, unit, rule, rows, **extra):
    result = dict(title=title, objective='Demanda, movilidad y operación de la red', units=unit,
                filters='Fuentes verificadas de la corrida e iteración seleccionadas',
                denominators='Conteos por intervalo; no normalizados por N',
                calculation=rule, observations=len(rows), exclusions='Campos ausentes conservados como null')
    result.update(extra)
    return result


def temporal_views(bundle):
    """Resolve published 15-minute metrics or an explicit hourly census fallback."""
    if bundle.get('temporal_rows'):
        rows = numeric_rows(bundle['temporal_rows'])
        if bundle.get('temporal_resolution') == 'hourly':
            rows = aggregate_temporal(rows)
        for row in rows:
            row['hour'] = row['start_seconds']/3600
        return rows, 'native_temporal', 'Resolución original de la fuente; conteos por intervalo y medias integrales.'
    if bundle.get('balanced_hours') and bundle.get('balanced_report', {}).get('schema_version') == 'simz1-balanced-launch-report-v2':
        rows = numeric_rows(bundle['balanced_hours'])
        for row in rows:
            row['hour_end'] = row['hour'] + 1
        return rows, 'fixed_day_hourly', 'Fuente horaria publicada. No existe serie de 15 minutos en este paquete.'
    return [], None, 'Sin fuente temporal publicada compatible.'


def _render_temporal(bundle, publisher, produced):
    rows, source, note = temporal_views(bundle)
    if not rows:
        return
    plt = _plt()
    fig, axes = plt.subplots(3, 1, figsize=(12, 8.5), sharex=True)
    if source == 'native_temporal':
        fields = [('planned_main', 'Salidas programadas: cohorte principal', 'Solicitudes / intervalo', COLORS['planned']),
                  ('departures_main', 'Salidas observadas: cohorte principal', 'Salidas / intervalo', COLORS['departure']),
                  ('entries_main', 'Incorporaciones nativas: cohorte principal', 'Incorporaciones / intervalo', COLORS['entry'])]
    else:
        fields = [('scheduled_requests', 'Salidas programadas: todas las familias', 'Solicitudes / hora', COLORS['planned']),
                  ('departures', 'Salidas observadas: todas las familias', 'Salidas / hora', COLORS['departure']),
                  ('incorporations', 'Incorporaciones a la red: todas las familias', 'Incorporaciones / hora', COLORS['entry'])]
    for ax, (key, label, unit, color) in zip(axes, fields):
        _line(ax, rows, key, label, color, drawstyle='steps-post')
        ax.set_ylabel(unit); _time_axis(ax, bundle); _legend(ax)
    title = 'Demanda programada, salidas e incorporación'
    _heading(fig, title, bundle, note)
    publisher.save(fig, 'demanda_salida_insercion', rows, _metadata(title, 'Solicitudes / salidas / incorporaciones por intervalo, en paneles separados',
                   'Conteos de la fuente; una salida observada no acredita entrada a la red.', rows, source_kind=source))
    produced.append('demanda_salida_insercion')

    fig, axes = plt.subplots(2, 1, figsize=(12, 7.8), sharex=True)
    if source == 'native_temporal':
        for field, label, color, style in [('active_mean_main', 'Activos principales: media integral', COLORS['active'], '-'),
                ('active_end_main', 'Activos principales: al corte', COLORS['active'], ':'),
                ('active_mean_context', 'Activos de contexto: media integral', '#94a3b8', '-'),
                ('active_mean_public', 'Buses activos: media integral', COLORS['bus'], '-')]:
            _line(axes[0], rows, field, label, color, linestyle=style)
        _line(axes[1], rows, 'pending_mean_main', 'Pendientes principales: media integral', COLORS['pending'])
        _line(axes[1], rows, 'pending_end_main', 'Pendientes principales: al corte', COLORS['pending'], linestyle=':')
        axes[1].set_ylabel('Personas pendientes')
    else:
        _line(axes[0], rows, 'active_non_public', 'No públicos: al cierre de la hora', COLORS['active'], x_key='hour_end')
        _line(axes[0], rows, 'active_public_vehicles', 'Buses físicos: al cierre de la hora', COLORS['bus'], x_key='hour_end')
        _line(axes[1], rows, 'waiting_non_public', 'Vehículos no públicos esperando incorporación', COLORS['pending'], x_key='hour_end')
        axes[1].set_ylabel('Vehículos pendientes')
    axes[0].set_ylabel('Vehículos activos')
    for ax in axes:
        _time_axis(ax, bundle); _legend(ax)
    title = 'Ocupación de la red y espera de incorporación'
    _heading(fig, title, bundle, note + '\nLas fotografías de ocupación no se suman como vehículos únicos.')
    publisher.save(fig, 'ocupacion_y_pendientes', rows, _metadata(title, 'Vehículos activos; personas o vehículos pendientes según panel y fuente',
                   'Promedio integral o fotografía al cierre, rotulados por separado. No se deriva de WAIT.', rows, source_kind=source))
    produced.append('ocupacion_y_pendientes')

    fig, axes = plt.subplots(2, 1, figsize=(12, 7.4), sharex=True)
    if source == 'native_temporal':
        for ax, suffix, label in [(axes[0], 'main', 'Cohorte principal'), (axes[1], 'public', 'Transporte público')]:
            _line(ax, rows, 'arrivals_'+suffix, label+': llegadas', COLORS['arrival'])
            _line(ax, rows, 'traffic_exits_'+suffix, label+': salidas del tráfico', COLORS['entry'], linestyle='--')
            ax.set_ylabel('Eventos / intervalo')
    else:
        _line(axes[0], rows, 'departures', 'Salidas observadas', COLORS['departure'])
        _line(axes[1], rows, 'real_arrivals', 'Llegadas reales', COLORS['arrival'])
        for ax in axes:
            ax.set_ylabel('Eventos / hora')
        note += '\nSalidas del tráfico no disponibles por hora; no se igualan a las llegadas.'
    for ax in axes:
        _time_axis(ax, bundle); _legend(ax)
    title = 'Llegadas y salidas observadas'
    _heading(fig, title, bundle, note)
    publisher.save(fig, 'llegadas_y_salidas', rows, _metadata(title, 'Eventos por intervalo de observación',
                   'Llegada, salida de viaje y salida del tráfico conservan sus definiciones nativas.', rows, source_kind=source))
    produced.append('llegadas_y_salidas')


def cohort_view(bundle):
    if bundle.get('cohort_rows'):
        selected = [r for r in numeric_rows(bundle['cohort_rows']) if r.get('cohort') == 'main']
        for row in selected:
            row['hour'] = row['planned_hour_relative_to_study']
        return selected, [('completed', 'Completos', '#009e73'), ('aborted', 'Abortados', '#d55e00'),
                          ('censored_never_entered', 'Censurados sin entrar', '#e69f00'),
                          ('censored_entered', 'Censurados que circularon', '#64748b')], 'trips'
    report = bundle.get('balanced_report', {})
    if report.get('schema_version') != 'simz1-balanced-launch-report-v2' or not bundle.get('balanced_groups'):
        return [], [], None
    groups = defaultdict(lambda: defaultdict(float))
    keys = ['scheduled_requests', 'completed', 'aborted_before_cut', 'active_at_cut',
            'waiting_for_incorporation', 'scheduled_not_departed', 'exited_without_arrival']
    for row in numeric_rows(bundle['balanced_groups']):
        if row['family'] == 'bus':
            continue  # Public expeditions have their own figure/denominator.
        hour = int(row['scheduled_hour'])
        for key in keys:
            # Fixed-day schema exports sparse Counter categories: absence = zero.
            groups[hour][key] += number(row.get(key)) or 0
    rows = [dict(hour=h, **dict(groups[h])) if h in groups else dict(hour=h) for h in range(max([24]+[h+1 for h in groups]))]
    return rows, [('completed', 'Completos', '#009e73'), ('aborted_before_cut', 'Abortados antes del corte', '#d55e00'),
                  ('active_at_cut', 'Activos al corte', '#64748b'), ('waiting_for_incorporation', 'Pendientes de incorporación', '#e69f00'),
                  ('scheduled_not_departed', 'Sin salida observada', '#8064a2'), ('exited_without_arrival', 'Salida de tráfico sin llegada', '#cc79a7')], 'scheduled_requests'


def _render_cohorts(bundle, publisher, produced):
    rows, fields, denominator = cohort_view(bundle)
    if not rows:
        return
    plt = _plt()
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for field, label, color in fields:
        _line(axes[0], rows, field, label, color, marker='o', markersize=3)
    plotted = []
    for row in rows:
        count = row.get(denominator)
        completed = row.get('completed')
        plotted.append(dict(row, completion_percent=100*completed/count if count and completed is not None else None))
    _line(axes[1], plotted, 'completion_percent', 'Completos / '+('salidas observadas' if denominator == 'trips' else 'solicitudes programadas'), '#009e73', marker='o', markersize=3)
    axes[0].set_ylabel('Viajes por cohorte')
    axes[1].set_ylabel('Completitud (%)'); axes[1].set_ylim(0, 100)
    for ax in axes:
        _time_axis(ax, bundle); _legend(ax)
    title = 'Cohortes horarias y estado al corte'
    _heading(fig, title, bundle, 'No públicos. Hora de salida programada de la cohorte; no es hora de llegada.\nUna solicitud sin salida observada no tiene duración completada.')
    publisher.save(fig, 'cohortes_y_censura', plotted, _metadata(title, 'Viajes y porcentaje, en paneles separados',
                   'Agregación por cohorte programada, familias no públicas. Porcentaje = completos / denominador explícito.', plotted,
                   denominator_field=denominator, sparse_zero_basis='simz1-balanced-launch-report-v2 Counter categories, only for fixed-day source'))
    produced.append('cohortes_y_censura')


def operational_views(bundle):
    intervals = numeric_rows(bundle.get('operational_intervals', []))
    prior = -1
    cumulative = 0
    for row in intervals:
        now = number(row['time'])
        if now <= prior:
            raise ValueError('Duplicate or unordered progress interval')
        prior = now
        elapsed = number(row.get('elapsed_sim_seconds'))
        row['hour'] = now/3600
        for key in ('wait_signal', 'wait_storage', 'wait_priority', 'wait_congestion', 'link_transitions', 'arrivals'):
            raw = number(row.get(key))
            row[key+'_per_second'] = raw/elapsed if raw is not None and elapsed and elapsed > 0 else None
        forced = number(row.get('forced_moves'))
        cumulative = cumulative+forced if forced is not None and cumulative is not None else None
        row['forced_moves_cumulative'] = cumulative
    return intervals


def _render_operational(bundle, publisher, produced):
    rows = operational_views(bundle)
    if not rows:
        return
    plt = _plt()
    hourly = numeric_rows(bundle.get('operational_hourly', []))
    def panel(ax, kind):
        if kind == 'activity':
            _line(ax, rows, 'active_vehicles', 'Fotografía nativa', COLORS['active'])
            ax.set_title('Actividad vehicular'); ax.set_ylabel('Vehículos activos')
        elif kind == 'events':
            _line(ax, rows, 'link_transitions_per_second', 'Transiciones entre enlaces', COLORS['entry'])
            _line(ax, rows, 'arrivals_per_second', 'Llegadas', COLORS['arrival'])
            ax.set_title('Flujo de eventos por intervalo nativo'); ax.set_ylabel('Eventos / segundo simulado')
        elif kind == 'wait':
            for key, label, color in [('wait_signal', 'Señal', '#0072b2'), ('wait_storage', 'Almacenamiento', '#d55e00'),
                    ('wait_priority', 'Prioridad', '#009e73'), ('wait_congestion', 'Congestión', '#8064a2')]:
                _line(ax, rows, key+'_per_second', label, color)
            ax.set_title('Frecuencia de decisiones WAIT'); ax.set_ylabel('Intentos / segundo simulado')
        else:
            _line(ax, rows, 'forced_moves_cumulative', 'Movimientos forzados', '#d55e00', drawstyle='steps-post')
            removals = bundle.get('operational_report', {}).get('native', {}).get('storage_stuck_removals')
            label = f'Remociones por almacenamiento: {removals}' if removals is not None else 'Remociones por almacenamiento: no disponibles'
            ax.text(.02, .83, label+'\nTotal auditado; sin ubicación temporal.', transform=ax.transAxes, va='top', fontsize=9)
            ax.set_title('Movimientos forzados y remociones'); ax.set_ylabel('Movimientos acumulados')
        _time_axis(ax, bundle); _legend(ax)
    note = 'WAIT cuenta intentos: no son vehículos distintos, segundos de espera ni longitud de cola.\nLas tasas dividen cada delta por la duración real de su intervalo; no por una hora supuesta.'
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, kind in zip(axes.flat, ('activity', 'events', 'wait', 'forced')):
        panel(ax, kind)
    title = 'Cronología operativa'
    _heading(fig, title, bundle, note)
    publisher.save(fig, 'operational_timeline', rows, _metadata(title, 'Vehículos; eventos/s; intentos/s; movimientos, en paneles separados',
                   'Tasas por intervalo nativo; activos son gauges; forzados son suma de deltas conocidos.', rows,
                   removals_total=bundle.get('operational_report', {}).get('native', {}).get('storage_stuck_removals')))
    produced.append('operational_timeline')
    # Single-column companion is legible on a thesis page; original name remains.
    fig, axes = plt.subplots(4, 1, figsize=(12, 14), sharex=True)
    for ax, kind in zip(axes, ('activity', 'events', 'wait', 'forced')):
        panel(ax, kind)
    _heading(fig, 'Cronología operativa · paneles ampliados', bundle, note)
    publisher.save(fig, 'operational_timeline_ampliado', rows, _metadata(title, 'Unidades separadas por panel',
                   'Mismos datos que operational_timeline; disposición vertical para lectura.', rows,
                   removals_total=bundle.get('operational_report', {}).get('native', {}).get('storage_stuck_removals')))
    produced.append('operational_timeline_ampliado')


def public_transport_view(bundle):
    report = bundle.get('balanced_report', {})
    public = report.get('public_transport', {})
    if not public:
        return []
    trips, counts = public.get('trips', {}), public.get('event_counts', {})
    configured = public.get('public_transport_vehicles_configured')
    vehicles = public.get('public_transport_vehicle_ids_in_traffic')
    return [dict(group='fleet', metric='Flota física configurada', value=number(configured), unit='vehículos físicos'),
            dict(group='fleet', metric='Vehículos únicos que circularon', value=len(vehicles) if isinstance(vehicles, list) else None, unit='vehículos físicos'),
            dict(group='expeditions', metric='Programadas', value=number(public.get('public_transport_departures_scheduled')), unit='expediciones'),
            dict(group='expeditions', metric='Iniciadas', value=number(public.get('observed_expedition_starts')), unit='expediciones'),
            dict(group='expeditions', metric='Completadas', value=number(trips.get('completed_trips')), unit='expediciones'),
            dict(group='expeditions', metric='Canceladas al cierre', value=number(counts.get('boundary_cancelled_duty_after_closing')), unit='expediciones')]


def _bar_labels(ax, labels, values, color):
    known = [(i, v) for i, v in enumerate(values) if v is not None]
    bars = ax.barh([i for i, _ in known], [v for _, v in known], color=color, height=.62)
    ax.bar_label(bars, labels=[f'{v:,.0f}' for _, v in known], padding=5, fontsize=10)
    ax.set_yticks(range(len(labels)), labels, fontsize=10)
    ax.invert_yaxis(); ax.set_xlim(left=0)
    if known:
        ax.set_xlim(0, max(v for _, v in known)*1.23 or 1)
    for i, v in enumerate(values):
        if v is None:
            ax.text(.02, i, 'No disponible', transform=ax.get_yaxis_transform(), va='center', color='#64748b')
    ax.grid(axis='x', alpha=.2); ax.set_axisbelow(True)
    ax.spines[['top', 'right']].set_visible(False)


def _render_services(bundle, publisher, produced):
    plt = _plt()
    rows = public_transport_view(bundle)
    if rows:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={'width_ratios': [1.1, 1.5]})
        for ax, group, unit, color in [(axes[0], 'fleet', 'Vehículos físicos', COLORS['bus']),
                                       (axes[1], 'expeditions', 'Expediciones', '#0072b2')]:
            selected = [r for r in rows if r['group'] == group]
            _bar_labels(ax, [r['metric'] for r in selected], [r['value'] for r in selected], color)
            ax.set_xlabel(unit)
        title = 'Transporte público: flota y expediciones'
        _heading(fig, title, bundle, 'Una unidad física puede realizar varias expediciones. Las categorías de expedición no son aditivas.\nCancelación al cierre conserva el evento nativo; ausencia de un contador no equivale a cero.')
        publisher.save(fig, 'transporte_publico_flota_expediciones', rows, _metadata(title, 'Vehículos físicos y expediciones, en paneles separados',
                       'Contadores auditados del informe balanced-launch; vehículos únicos por lista explícita.', rows,
                       exclusions='Ninguna imputación de cancelaciones; las mediciones ausentes son null'))
        produced.append('transporte_publico_flota_expediciones')
    freight = numeric_rows(bundle.get('freight_rows', []))
    if freight:
        categories = ['nominal', 'tolerated', 'excess_tolerance', 'pending_not_evaluable', 'technical_physical_error']
        names = ['Nominal', 'Dentro de tolerancia', 'Excede tolerancia', 'Pendiente no evaluable', 'Error físico/técnico']
        counts = {c: sum(r.get('classification') == c for r in freight) for c in categories}
        unknown = len(freight)-sum(counts.values())
        if unknown:
            categories.append('other'); names.append('Otra clasificación de la fuente'); counts['other'] = unknown
        grouped = defaultdict(lambda: defaultdict(int))
        for row in freight:
            group = (row.get('route_id'), row.get('window_close_seconds'), row.get('deadline_seconds'))
            grouped[group]['scheduled'] += 1
            grouped[group][row.get('classification') or 'missing_classification'] += 1
        numerical = [dict(route_id=key[0], window_close_seconds=key[1], deadline_seconds=key[2], **dict(value)) for key, value in sorted(grouped.items(), key=str)]
        fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={'width_ratios':[1.25,1.4]})
        _bar_labels(axes[0], names, [counts[c] for c in categories], COLORS['freight'])
        axes[0].set_xlabel('Expediciones de carga')
        delays = [number(r.get('delay_seconds'))/60 for r in freight if r.get('delay_seconds') is not None and r.get('trip_outcome') == 'completed']
        histogram = []
        if delays:
            if any(value < 0 for value in delays):
                raise ValueError('Negative delay is incompatible with delay_seconds definition')
            heights, edges, _ = axes[1].hist(delays, bins=min(20, max(1, math.ceil(math.sqrt(len(delays))))),
                                           range=(0, max(1, max(delays)*1.05)), color=COLORS['freight'], edgecolor='white')
            histogram = [dict(left_minutes=float(edges[i]), right_minutes=float(edges[i+1]), count=int(v)) for i, v in enumerate(heights)]
        else:
            axes[1].text(.5, .5, 'Sin expediciones completas con retraso disponible', transform=axes[1].transAxes, ha='center')
        axes[1].set(xlabel='Retraso respecto al cierre de ventana (min)', ylabel='Expediciones completas', xlim=(0, None), ylim=(0,None))
        axes[1].grid(axis='y', alpha=.22)
        title = 'Carga: clasificación y ventanas de servicio'
        _heading(fig, title, bundle, f'Muestra: {len(freight)} expediciones registradas; retrasos disponibles: {len(delays)}.\nSe conservan las clases, ventanas y plazos de la corrida. Los camiones están incluidos en N.')
        # Export source rows: histogram sample and route/window classifications are reproducible.
        publisher.save(fig, 'carga_clasificacion_ventanas', freight, _metadata(title, 'Expediciones; minutos de retraso',
                       'Clasificación original, sin recalcular el criterio de servicio; retraso en minutos = delay_seconds / 60.', freight,
                       route_windows=numerical, histogram_sample=len(delays), duration_exclusions=len(freight)-len(delays),
                       classification_counts=counts, histogram=histogram))
        produced.append('carga_clasificacion_ventanas')


def render_operations(bundle, publisher):
    """Render available summaries; no canonical file is created or modified."""
    produced = []
    _render_temporal(bundle, publisher, produced)
    _render_cohorts(bundle, publisher, produced)
    _render_operational(bundle, publisher, produced)
    _render_services(bundle, publisher, produced)
    pending = []
    if 'demanda_salida_insercion' not in produced:
        pending.append(dict(indicator='series_temporales', reason='Sin tablas temporales publicadas compatibles; no se leen eventos.'))
    if 'operational_timeline' not in produced:
        pending.append(dict(indicator='operational_timeline', reason='Sin intervalos de progreso verificados; no se infiere WAIT ni remociones.'))
    return dict(figures=produced, pending=pending)
