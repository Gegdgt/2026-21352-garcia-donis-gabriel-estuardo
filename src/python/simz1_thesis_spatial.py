"""Spatial thesis figures from verified published tables, without event replay.

The caller verifies the run, table and network hashes. OD candidates are observed
endpoints, never an invented route or a formally selected A–B measurement.
"""
from __future__ import annotations

import csv
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection


COLORS = ('#0072B2', '#D55E00', '#009E73', '#CC79A7')


def read_network(path):
    """Retain only native node/link geometry; no XML tree or route reconstruction."""
    opener = gzip.open if str(path).endswith('.gz') else open
    nodes, links, crs = {}, {}, None
    with opener(path, 'rb') as stream:
        for _, element in ET.iterparse(stream, events=('end',)):
            if element.tag == 'attribute' and element.get('name') == 'coordinateReferenceSystem':
                crs = element.text
            elif element.tag == 'node':
                x, y = float(element.attrib['x']), float(element.attrib['y'])
                if not all(math.isfinite(v) for v in (x, y)):
                    raise ValueError('Coordenadas de red no finitas')
                ident = element.attrib['id']
                if ident in nodes:
                    raise ValueError('Nodo duplicado')
                nodes[ident] = (x, y)
                element.clear()
            elif element.tag == 'link':
                ident = element.attrib['id']
                if ident in links:
                    raise ValueError('Enlace duplicado')
                links[ident] = (element.attrib['from'], element.attrib['to'])
                element.clear()
    if not nodes or not links or any(a not in nodes or b not in nodes for a, b in links.values()):
        raise ValueError('Red ausente o enlaces con nodos no definidos')
    return nodes, links, crs


def trip_rows(path, identity):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'run_id', 'iteration', 'departure_link', 'arrival_link', 'status', 'departure', 'duration_seconds'}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError('Tabla de viajes sin extremos o identidad explícitos')
        for row in reader:
            if row['run_id'] != identity['run_id'] or int(row['iteration']) != identity['iteration']:
                raise ValueError('Identidad de viaje incompatible con la corrida seleccionada')
            yield row


def candidate_pairs(path, identity, links, limit=4):
    """Exact counts on disk: RAM depends on network/selected pairs, never on N."""
    observed = excluded = 0
    with tempfile.TemporaryDirectory(prefix='simz1-thesis-od-') as temporary:
        with closing(sqlite3.connect(str(Path(temporary) / 'pairs.sqlite'))) as db:
            db.execute('CREATE TABLE pairs (a TEXT, b TEXT, n INTEGER, PRIMARY KEY(a,b)) WITHOUT ROWID')
            for row in trip_rows(path, identity):
                observed += 1
                a, b = row['departure_link'], row['arrival_link']
                if row['status'] != 'completed' or not a or not b or a == b:
                    excluded += 1
                    continue
                if a not in links or b not in links:
                    raise ValueError('Extremo observado ausente de la red verificada')
                db.execute('INSERT INTO pairs VALUES (?,?,1) ON CONFLICT(a,b) DO UPDATE SET n=n+1', (a, b))
            db.commit()
            rows = [dict(candidate=i + 1, origin_link=a, destination_link=b, completed_observations=n)
                    for i, (a, b, n) in enumerate(db.execute('SELECT a,b,n FROM pairs ORDER BY n DESC,a,b LIMIT ?', (limit,)))]
            count = db.execute('SELECT COUNT(*) FROM pairs').fetchone()[0]
    return rows, dict(table_observations=observed, excluded_observations=excluded,
                      eligible_observations=observed - excluded, eligible_distinct_pairs=count,
                      shown_observations=sum(r['completed_observations'] for r in rows))


def _subtitle(identity):
    n = identity.get('N_configured', identity.get('n_configured', identity.get('N')))
    return f"N configurado: {n if n is not None else 'no disponible'} · iteración {identity['iteration']}"


def _separate_annotations(fig, ax, annotations):
    """Move labels in display coordinates, preserving every native map point."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    occupied = []
    for annotation in annotations:
        original = annotation.get_position()
        candidates = [(original[0], original[1], 'left', 'baseline'),
                      (-8, 8, 'right', 'bottom'), (8, -14, 'left', 'top'),
                      (-8, -14, 'right', 'top'), (0, 22, 'center', 'bottom'),
                      (0, -26, 'center', 'top'), (20, 16, 'left', 'bottom'),
                      (-20, 16, 'right', 'bottom')]
        candidates += [(0, offset, 'center', 'bottom' if offset > 0 else 'top')
                       for offset in (35, -35, 50, -50, 65, -65)]
        for x, y, ha, va in candidates:
            annotation.set_position((x, y)); annotation.set_ha(ha); annotation.set_va(va)
            box = annotation.get_window_extent(renderer).expanded(1.07, 1.2)
            inside = (box.x0 >= ax.bbox.x0 and box.x1 <= ax.bbox.x1 and
                      box.y0 >= ax.bbox.y0 and box.y1 <= ax.bbox.y1)
            if inside and not any(box.overlaps(previous) for previous in occupied):
                occupied.append(box)
                break
        else:
            raise ValueError('No se pudo colocar una etiqueta de candidato sin solapamiento')


def render_candidates(bundle, publisher):
    identity = bundle['identity']
    nodes, links, crs = read_network(bundle['network_path'])
    rows, counts = candidate_pairs(bundle['trips_path'], identity, links)
    if not rows:
        return {'status': 'pending', 'reason': 'No hay pares de extremos observados compatibles en la tabla.', **counts}
    xmin = min(p[0] for p in nodes.values())
    ymin = min(p[1] for p in nodes.values())
    metric = crs and ('326' in crs or '327' in crs)
    factor = 1000 if metric else 1
    def point(node):
        x, y = nodes[node]
        return ((x - xmin) / factor, (y - ymin) / factor)
    segments = [[point(a), point(b)] for a, b in links.values()]
    fig, (ax, details) = plt.subplots(1, 2, figsize=(13, 8), gridspec_kw={'width_ratios': [1.7, 1]})
    ax.add_collection(LineCollection(segments, colors='#a8b1bc', linewidths=.45, alpha=.48))
    ax.autoscale()
    ax.set_aspect('equal')
    ax.set_xlabel('Este local (km)' if metric else 'X relativo (unidades nativas)')
    ax.set_ylabel('Norte local (km)' if metric else 'Y relativo (unidades nativas)')
    ax.grid(alpha=.13)
    details.axis('off')
    markers = {}
    for row, color in zip(rows, COLORS):
        number = row['candidate']
        for key, letter, marker in [('origin_link', 'A', 'o'), ('destination_link', 'B', '^')]:
            a, b = links[row[key]]
            p, q = point(a), point(b)
            center = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            markers.setdefault(row[key], []).append(dict(label=f'{letter}{number}', letter=letter,
                                                         marker=marker, color=color, center=center, p=p, q=q))
            row[f'{key}_from_node'] = a
            row[f'{key}_to_node'] = b
            row[f'{key}_x'] = (nodes[a][0] + nodes[b][0]) / 2
            row[f'{key}_y'] = (nodes[a][1] + nodes[b][1]) / 2
        y = .97 - (number - 1) * .22
        details.text(0, y, f"Candidato {number} · {row['completed_observations']} viajes completos", color=color,
                     fontsize=11, weight='bold', va='top')
        details.text(0, y - .05, f"A{number}: {row['origin_link']}\nB{number}: {row['destination_link']}",
                     fontsize=8.8, va='top', linespacing=1.65)
    annotations = []
    for observations in markers.values():
        first = observations[0]
        color = first['color'] if len(observations) == 1 else '#334155'
        label = ', '.join(item['label'] for item in observations)
        p, q = first['p'], first['q']
        ax.plot([p[0], q[0]], [p[1], q[1]], color=color, lw=2.4)
        ax.scatter(*first['center'], marker=first['marker'], c=color, s=52, edgecolors='white', zorder=4)
        annotations.append(ax.annotate(label, first['center'], xytext=(7, 8 if first['letter'] == 'A' else -13),
                           textcoords='offset points', color=color, fontsize=10, weight='bold',
                           bbox=dict(boxstyle='round,pad=.15', facecolor='white', edgecolor='none', alpha=.87)))
    fig.suptitle('Pares de enlaces candidatos para el indicador A–B', fontsize=17, weight='bold', y=.97)
    fig.text(.5, .925, _subtitle(identity), ha='center', color='#475569', fontsize=11)
    fig.text(.06, .055, 'Marcadores: A = enlace de salida; B = enlace de llegada. No se dibuja un recorrido.\n'
             f"Selección: mayor número de viajes completos por par dirigido; desempate lexicográfico. Muestra: {counts['eligible_observations']} viajes elegibles.\n"
             'Candidatos sin selección formal A–B: no se publica un tiempo. Geometría importada; no es cartografía GIS verificada.',
             fontsize=9, color='#475569', linespacing=1.5)
    fig.subplots_adjust(top=.88, bottom=.17, left=.07, right=.98, wspace=.22)
    _separate_annotations(fig, ax, annotations)
    publisher.save(fig, 'candidatos_ab', rows, dict(
        title='Pares de enlaces candidatos para el indicador A–B', objective='Tiempo entre punto A y punto B',
        status='candidate_selection_pending', unit='viajes completos con ambos extremos observados',
        filters='completed; extremos distintos y presentes en la red de esta corrida; sin tiempos A–B publicados',
        denominators=counts, calculation='COUNT(*) por (departure_link,arrival_link); top 4 por n descendente y enlaces lexicográficos',
        observations=counts['shown_observations'], exclusions=counts['excluded_observations'],
        source_names=['trips.csv.gz', 'network'], coordinate_reference=crs,
        local_coordinate_origin=dict(x=xmin, y=ymin), selected_route=False,
        limitation='Candidatos reproducibles, no par A–B formal. Sin estimación de tiempo ni trayectoria.'))
    return {'status': 'candidates_published', **counts}


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def ab_hourly(bundle):
    """Explicit A/B departure/arrival semantics; quantiles sorted by SQLite on disk."""
    definition = bundle['ab_definition']
    if definition.get('time_basis') != 'departure' or definition.get('duration_definition') != 'arrival_minus_departure':
        raise ValueError('La definición A–B requiere hora de salida y llegada menos salida')
    if definition.get('network_sha256') != _sha(bundle['network_path']):
        raise ValueError('La definición A–B pertenece a otra red')
    _, links, _ = read_network(bundle['network_path'])
    a, b = definition['origin_link'], definition['destination_link']
    if a not in links or b not in links or a == b:
        raise ValueError('Definición A–B sin dos enlaces distintos de la red')
    horizon = bundle['identity'].get('horizon', bundle['identity'].get('time_horizon', {}))
    start = float(horizon.get('start_seconds', 0))
    end = float(horizon.get('end_seconds', 86400))
    if not 0 <= start < end or not all(math.isfinite(v) for v in (start, end)):
        raise ValueError('Horizonte A–B inválido')
    total = excluded = 0
    with tempfile.TemporaryDirectory(prefix='simz1-thesis-ab-') as temporary:
        with closing(sqlite3.connect(str(Path(temporary) / 'durations.sqlite'))) as db:
            db.execute('CREATE TABLE durations (hour INTEGER, minutes REAL)')
            for row in trip_rows(bundle['trips_path'], bundle['identity']):
                total += 1
                if row['status'] != 'completed' or row['departure_link'] != a or row['arrival_link'] != b:
                    excluded += 1
                    continue
                departure, duration = float(row['departure']), float(row['duration_seconds'])
                if not all(math.isfinite(v) for v in (departure, duration)) or duration < 0:
                    raise ValueError('Tiempo A–B no finito o negativo')
                if not start <= departure < end:
                    excluded += 1
                    continue
                db.execute('INSERT INTO durations VALUES (?,?)', (math.floor(departure / 3600), duration / 60))
            db.execute('CREATE INDEX durations_hour_time ON durations(hour,minutes)')
            rows = []
            for hour in range(math.floor(start / 3600), math.ceil(end / 3600)):
                n, mean = db.execute('SELECT COUNT(*),AVG(minutes) FROM durations WHERE hour=?', (hour,)).fetchone()
                def quantile(p):
                    if not n:
                        return None
                    index = (n - 1) * p
                    lo, hi = math.floor(index), math.ceil(index)
                    left = db.execute('SELECT minutes FROM durations WHERE hour=? ORDER BY minutes LIMIT 1 OFFSET ?', (hour, lo)).fetchone()[0]
                    right = db.execute('SELECT minutes FROM durations WHERE hour=? ORDER BY minutes LIMIT 1 OFFSET ?', (hour, hi)).fetchone()[0]
                    return left + (right - left) * (index - lo)
                rows.append(dict(hour=hour, n_completed=n, mean_minutes=mean, median_minutes=quantile(.5), p95_minutes=quantile(.95),
                                 origin_link=a, destination_link=b))
    return rows, {'table_observations': total, 'excluded_observations': excluded, 'n_completed': total - excluded}


def render_ab(bundle, publisher):
    rows, counts = ab_hourly(bundle)
    fig, (ax, sample) = plt.subplots(2, 1, figsize=(12, 7.5), sharex=True,
                                    gridspec_kw={'height_ratios': [3, 1]})
    for key, label, color, style in [('mean_minutes', 'Media', COLORS[0], '-'),
                                    ('median_minutes', 'Mediana', COLORS[2], '--'),
                                    ('p95_minutes', 'P95', COLORS[1], ':')]:
        ax.plot([r['hour'] + .5 for r in rows], [r[key] if r[key] is not None else math.nan for r in rows],
                label=label, color=color, ls=style, marker='o', ms=3)
    ax.set_ylabel('Duración (minutos)')
    ax.set_ylim(bottom=0)
    ax.grid(alpha=.2)
    ax.legend(ncol=3)
    sample.bar([r['hour'] + .5 for r in rows], [r['n_completed'] for r in rows], color=COLORS[0], width=.8)
    sample.set_ylabel('Viajes\ncompletos')
    sample.set_xlabel('Hora de salida observada')
    sample.set_xticks([r['hour'] for r in rows][::2] + [rows[-1]['hour'] + 1])
    sample.set_xticklabels([f'{int(v):02d}:00' for v in sample.get_xticks()])
    sample.set_xlim(rows[0]['hour'], rows[-1]['hour'] + 1)
    fig.suptitle('Tiempo de viaje entre los enlaces A y B', fontsize=17, weight='bold', y=.98)
    fig.text(.5, .93, _subtitle(bundle['identity']) + f" · n = {counts['n_completed']}", ha='center', fontsize=11)
    fig.text(.07, .035, 'Duración: llegada menos salida observadas; incluye espera de incorporación. Horas vacías = sin observaciones.\n'
             'Sólo viajes completos con ambos extremos exactos; los demás registros se excluyen, sin imputar duraciones.', fontsize=9)
    fig.subplots_adjust(top=.87, bottom=.15, hspace=.15, left=.09, right=.98)
    publisher.save(fig, 'tiempo_ab_por_hora', rows, dict(
        title='Tiempo de viaje entre los enlaces A y B', objective='Tiempo entre punto A y punto B', unit='minutos y viajes completos',
        filters=bundle['ab_definition'], denominators=counts,
        calculation='(arrival-departure)/60; mediana y P95 por interpolación lineal de observaciones individuales en cada hora',
        observations=counts['n_completed'], exclusions=counts['excluded_observations'],
        source_names=['trips.csv.gz', 'network', 'ab_definition'],
        limitation='No estima tiempo de paso por enlaces interiores: usa los extremos observados del viaje.'))
    return {'status': 'published', **counts}


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Indicador contiene un valor no finito')
    if isinstance(value, dict):
        for item in value.values(): _finite(item)
    elif isinstance(value, list):
        for item in value: _finite(item)


def _record(path, kind):
    return dict(path=str(path), sha256=_sha(path), bytes=Path(path).stat().st_size,
                kind=kind, verification='supplemental indicator identity/schema/hash contract; no native event rescan')


def _rows(path, identity, fields):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'run_id', 'iteration', *fields}.issubset(reader.fieldnames or ()):
            raise ValueError('CSV de indicador sin columnas obligatorias')
        for row in reader:
            if row['run_id'] != identity['run_id'] or int(row['iteration']) != identity['iteration']:
                raise ValueError('Identidad de indicador incompatible')
            yield row


def section_hourly(path, identity, sections, coverage, network_links=None):
    """Deduplicate actual crossing records per vehicle, directed section and hour."""
    memberships = {}
    for section in sections:
        for link in section['boundary_links']:
            memberships.setdefault(link, []).append(section['id'])
    start, end = coverage['start_seconds'], coverage['end_seconds']
    horizon = identity.get('horizon', identity.get('time_horizon', {}))
    first, last = math.floor(horizon['start_seconds'] / 3600), math.ceil(horizon['end_seconds'] / 3600)
    observations = exclusions = accepted = 0
    with tempfile.TemporaryDirectory(prefix='simz1-thesis-sections-') as temporary:
        with closing(sqlite3.connect(str(Path(temporary) / 'crossings.sqlite'))) as db:
            db.execute('CREATE TABLE seen (section TEXT, hour INTEGER, vehicle TEXT, PRIMARY KEY(section,hour,vehicle)) WITHOUT ROWID')
            for row in _rows(path, identity, {'time_seconds', 'vehicle_id', 'link_id'}):
                observations += 1
                time = float(row['time_seconds'])
                if not math.isfinite(time) or not start <= time < end or not row['vehicle_id']:
                    raise ValueError('Cruce sin vehículo o fuera de la cobertura declarada')
                if network_links is not None and row['link_id'] not in network_links:
                    raise ValueError('Cruce en enlace ausente de la red verificada')
                if row['link_id'] not in memberships:
                    exclusions += 1
                    continue
                accepted += 1
                for section in memberships[row['link_id']]:
                    db.execute('INSERT OR IGNORE INTO seen VALUES (?,?,?)', (section, math.floor(time / 3600), row['vehicle_id']))
            counts = {(section, hour): n for section, hour, n in db.execute('SELECT section,hour,COUNT(*) FROM seen GROUP BY section,hour')}
            rows = []
            for section in sections:
                for hour in range(first, last):
                    seconds = max(0., min(end, (hour + 1) * 3600) - max(start, hour * 3600))
                    n = counts.get((section['id'], hour), 0) if seconds else None
                    rows.append(dict(section_id=section['id'], section_label=section['label'], direction=section['direction'],
                                     hour=hour, distinct_vehicles=n, coverage_seconds=seconds,
                                     vehicles_per_hour=n if seconds == 3600 else None))
    return rows, dict(raw_crossing_records=observations, excluded_other_links=exclusions,
                      selected_crossing_records=accepted, section_vehicle_hour_observations=sum(counts.values()),
                      denominator='one complete 3600-second bin; no extrapolation from partial bins')


def intersection_hourly(path, identity, definition, coverage):
    """Time-weighted occupancy, rejecting overlap and retaining gaps as missing."""
    ids = {item['id']: item for item in definition['intersections']}
    horizon = identity.get('horizon', identity.get('time_horizon', {}))
    first, last = math.floor(horizon['start_seconds'] / 3600), math.ceil(horizon['end_seconds'] / 3600)
    sums, covered, seen_end = {}, {}, {}
    observations = 0
    # Required ordering permits overlap validation with bounded state per node.
    prior_key = None
    for row in _rows(path, identity, {'intersection_id', 'start_seconds', 'end_seconds', 'occupancy_vehicles'}):
        ident = row['intersection_id']
        start, end, occupancy = (float(row[k]) for k in ('start_seconds', 'end_seconds', 'occupancy_vehicles'))
        if ident not in ids or not all(math.isfinite(v) for v in (start, end, occupancy)):
            raise ValueError('Intersección desconocida o valor no finito')
        if not coverage['start_seconds'] <= start < end <= coverage['end_seconds'] or occupancy < 0 or not occupancy.is_integer():
            raise ValueError('Intervalo de ocupación o conteo inválido')
        key = ident, start
        if prior_key is not None and key <= prior_key:
            raise ValueError('Intervalos deben ordenarse por intersección y tiempo sin duplicados')
        prior_key = key
        if start < seen_end.get(ident, -math.inf):
            raise ValueError('Intervalos de ocupación superpuestos')
        seen_end[ident] = end
        observations += 1
        for hour in range(math.floor(start / 3600), math.ceil(end / 3600)):
            seconds = max(0., min(end, (hour + 1) * 3600) - max(start, hour * 3600))
            key = ident, hour
            sums[key] = sums.get(key, 0.) + seconds * occupancy
            covered[key] = covered.get(key, 0.) + seconds
    rows = []
    for ident, item in ids.items():
        for hour in range(first, last):
            key = ident, hour
            seconds = covered.get(key, 0.)
            rows.append(dict(intersection_id=ident, intersection_label=item['label'], node_id=item['node_id'],
                             hour=hour, covered_seconds=seconds,
                             occupancy_vehicle_seconds=sums.get(key) if seconds else None,
                             mean_occupancy_vehicles=sums.get(key, 0.) / 3600 if seconds == 3600 else None))
    return rows, dict(source_intervals=observations, complete_intersection_hours=sum(r['covered_seconds'] == 3600 for r in rows),
                      missing_or_partial_intersection_hours=sum(r['covered_seconds'] != 3600 for r in rows),
                      denominator='3600 covered seconds per intersection-hour; gaps/partial hours are missing')


def load_indicators(path, bundle):
    """Load an optional published indicator pack; never derive it from event XML.

    JSON contract ``simz1-thesis-indicators-v1`` requires run_id, iteration,
    manifest_sha256, network_sha256, source_events_sha256, source_version,
    population_scope='all_physical_vehicles' and
    coverage {start_seconds,end_seconds,complete:true}. ``definitions`` may hold:

    * ab: origin_link, destination_link, time_basis='departure',
      duration_definition='arrival_minus_departure'. Its pair is a formal user
      selection, not a candidate chosen by this module.
    * directed_sections: [{id,label,direction,boundary_links:[native link IDs]}].
    * intersection_occupancy: {unit:'vehicles',
      method:'time_weighted_piecewise_constant', physical_definition:...,
      intersections:[{id,label,node_id,link_ids:[incident native link IDs]}]}.

    ``files`` keys crossings/occupancy identify relative CSV paths and SHA256.
    Crossings CSV: run_id,iteration,time_seconds,vehicle_id,link_id. Occupancy CSV:
    run_id,iteration,intersection_id,start_seconds,end_seconds,occupancy_vehicles,
    sorted by intersection_id,start_seconds. Data are assumed to come from the
    declared native extractor; identity/hash/shape are checked here. This is not
    independent re-auditing of native events or physical measurement calibration.
    """
    path = Path(path).resolve()
    pack = json.loads(path.read_text(encoding='utf-8-sig'))
    _finite(pack)
    identity = bundle['identity']
    if pack.get('schema') != 'simz1-thesis-indicators-v1':
        raise ValueError('Esquema de indicadores incompatible')
    if type(pack.get('iteration')) is not int:
        raise ValueError('Iteración de indicador debe ser un entero')
    for key in ('run_id', 'iteration', 'manifest_sha256'):
        if pack.get(key) != identity.get(key):
            raise ValueError('Identidad del paquete de indicadores incompatible: ' + key)
    if pack.get('network_sha256') != _sha(bundle['network_path']):
        raise ValueError('Paquete de indicadores de otra red')
    events = bundle['manifest'].get('results', {}).get(str(identity['iteration']), {}).get('events', {})
    if not events.get('sha256') or pack.get('source_events_sha256') != events['sha256']:
        raise ValueError('Fuente de eventos del indicador incompatible')
    if not isinstance(pack.get('source_version'), str) or not pack['source_version'].strip():
        raise ValueError('Falta versión de la fuente de indicadores')
    if pack.get('population_scope') != 'all_physical_vehicles':
        raise ValueError('El alcance del indicador debe ser all_physical_vehicles; no normalizar una submuestra por la flota total')
    coverage = pack.get('coverage', {})
    horizon = identity.get('horizon', identity.get('time_horizon', {}))
    start, end = coverage.get('start_seconds'), coverage.get('end_seconds')
    if (type(start) not in (float, int) or type(end) not in (float, int) or
            not horizon['start_seconds'] <= start < end <= horizon['end_seconds'] or coverage.get('complete') is not True):
        raise ValueError('Cobertura de indicadores ausente o inválida')
    nodes, links, _ = read_network(bundle['network_path'])
    definitions = pack.get('definitions', {})
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError('Falta definición de indicadores')
    result = dict(definitions=definitions, source_version=pack['source_version'], coverage=coverage,
                  sources=[_record(path, 'supplemental_indicator_manifest')],
                  section_hour=[], occupancy_hour=[], section_statistics=None, occupancy_statistics=None)
    files = pack.get('files', {})
    def verified_file(name):
        record = files.get(name, {})
        rel = record.get('path')
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
            raise ValueError('Ruta de indicador inválida')
        source = (path.parent / rel).resolve()
        if not source.is_relative_to(path.parent) or not source.is_file() or _sha(source) != record.get('sha256'):
            raise ValueError('Archivo de indicador ausente, modificado o fuera de su paquete')
        result['sources'].append(_record(source, 'supplemental_' + name))
        return source
    if definitions.get('ab'):
        ab = dict(definitions['ab'], network_sha256=pack['network_sha256'])
        if (ab.get('origin_link') not in links or ab.get('destination_link') not in links or
                ab['origin_link'] == ab['destination_link'] or ab.get('time_basis') != 'departure' or
                ab.get('duration_definition') != 'arrival_minus_departure'):
            raise ValueError('Definición formal A–B inválida')
        result['ab_definition'] = ab
    sections = definitions.get('directed_sections', [])
    if sections:
        ids = set()
        for section in sections:
            ident, boundary = section.get('id'), section.get('boundary_links')
            if (not isinstance(ident, str) or not ident or ident in ids or not section.get('label') or not section.get('direction') or
                    not isinstance(boundary, list) or not boundary or len(boundary) != len(set(boundary)) or any(x not in links for x in boundary)):
                raise ValueError('Sección dirigida sin definición única en la red')
            orientations = {links[link] for link in boundary}
            if any((b, a) in orientations for a, b in orientations):
                raise ValueError('Una sección dirigida mezcla sentidos opuestos')
            ids.add(ident)
        result['section_hour'], result['section_statistics'] = section_hourly(verified_file('crossings'), identity, sections, coverage, links)
    occupancy = definitions.get('intersection_occupancy')
    if occupancy:
        if (occupancy.get('unit') != 'vehicles' or occupancy.get('method') != 'time_weighted_piecewise_constant' or
                not occupancy.get('physical_definition') or not occupancy.get('intersections')):
            raise ValueError('Definición de ocupación inválida; no se admite WAIT como ocupación')
        ids = set()
        for item in occupancy['intersections']:
            ident, node, domain = item.get('id'), item.get('node_id'), item.get('link_ids')
            if (not isinstance(ident, str) or not ident or ident in ids or node not in nodes or not item.get('label') or
                    not isinstance(domain, list) or not domain or len(domain) != len(set(domain)) or
                    any(link not in links or node not in links[link] for link in domain)):
                raise ValueError('Dominio de intersección incompatible con la red')
            ids.add(ident)
        result['occupancy_hour'], result['occupancy_statistics'] = intersection_hourly(verified_file('occupancy'), identity, occupancy, coverage)
    if not result.get('ab_definition') and not sections and not occupancy:
        raise ValueError('Paquete sin indicadores reconocidos')
    result['comparison_contract'] = dict(network_sha256=pack['network_sha256'], definitions=definitions,
                                         coverage=coverage, source_version=pack['source_version'],
                                         population_scope=pack['population_scope'])
    return result


def render_sections(bundle, publisher):
    indicators = bundle['indicators']
    rows = indicators['section_hour']
    sections = indicators['definitions']['directed_sections']
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for index, section in enumerate(sections):
        data = [r for r in rows if r['section_id'] == section['id']]
        ax.plot([r['hour'] + .5 for r in data], [r['vehicles_per_hour'] if r['vehicles_per_hour'] is not None else math.nan for r in data],
                marker='o', ms=3, label=f"{section['label']} · {section['direction']}", color=COLORS[index % len(COLORS)],
                ls=('-', '--', ':', '-.')[index // len(COLORS) % 4])
    start, end = min(r['hour'] for r in rows), max(r['hour'] for r in rows) + 1
    ax.set_xlim(start, end);ax.set_ylim(bottom=0)
    ax.set_xticks(range(start, end + 1, 2));ax.set_xticklabels([f'{x:02d}:00' for x in ax.get_xticks()])
    ax.set_xlabel('Hora de cruce observada');ax.set_ylabel('Vehículos distintos por hora y sección')
    ax.grid(alpha=.2);ax.legend(loc='upper left', bbox_to_anchor=(0, -.15), ncol=2)
    fig.suptitle('Flujo observado en secciones dirigidas', fontsize=17, weight='bold', y=.97)
    fig.text(.5, .915, _subtitle(bundle['identity']), ha='center', fontsize=11)
    fig.text(.06, .025, 'Cada vehículo cuenta una vez por sección y hora. No son cruces de enlaces ni expediciones.\n'
             'Franjas sin cobertura completa: sin indicador. Los registros repetidos no aumentan el flujo.', fontsize=9)
    fig.subplots_adjust(top=.86, bottom=.26, left=.09, right=.97)
    stats = indicators['section_statistics']
    publisher.save(fig, 'flujo_secciones', rows, dict(title='Flujo observado en secciones dirigidas', objective='Flujo en corredores',
        unit='vehículos distintos por hora y sección', filters=sections, denominators=stats,
        calculation='COUNT DISTINCT vehicle_id por sección dirigida y hora de cruce; no se suman enlaces',
        observations=stats['raw_crossing_records'], exclusions=stats['excluded_other_links'],
        source_names=['supplemental_crossings', 'supplemental_indicator_manifest'], coverage=indicators['coverage'],
        measurement_contract=indicators['comparison_contract']))


def render_intersections(bundle, publisher):
    import numpy as np
    indicators = bundle['indicators']; rows = indicators['occupancy_hour']
    items = indicators['definitions']['intersection_occupancy']['intersections']
    hours = sorted({r['hour'] for r in rows})
    lookup = {(r['intersection_id'], r['hour']): r['mean_occupancy_vehicles'] for r in rows}
    data = np.array([[lookup[(item['id'], hour)] if lookup[(item['id'], hour)] is not None else np.nan for hour in hours] for item in items])
    fig, ax = plt.subplots(figsize=(12, max(5., 2.7 + len(items) * .4)))
    cmap = plt.get_cmap('Blues').copy();cmap.set_bad('#e2e8f0')
    im = ax.imshow(np.ma.masked_invalid(data), aspect='auto', cmap=cmap, vmin=0,
                   vmax=max(1., float(np.nanmax(data))) if np.isfinite(data).any() else 1.)
    ax.set_yticks(range(len(items)));ax.set_yticklabels([item['label'] for item in items])
    ax.set_xticks(range(0, len(hours), 2));ax.set_xticklabels([f'{hours[x]:02d}:00' for x in range(0, len(hours), 2)])
    ax.set_xlabel('Hora de ocupación observada');ax.set_ylabel('Intersección / dominio definido')
    fig.colorbar(im, ax=ax, label='Ocupación media (vehículos)')
    fig.suptitle('Acumulación observada en intersecciones', fontsize=17, weight='bold', y=.97)
    fig.text(.5, .905, _subtitle(bundle['identity']), ha='center', fontsize=11)
    fig.text(.06, .035, 'Promedio ponderado por segundos: suma(vehículos × duración) / 3600. Gris = cobertura insuficiente.\n'
             'La ocupación corresponde al dominio definido en los datos; no se convierte a metros de cola ni a intentos WAIT.', fontsize=9)
    fig.subplots_adjust(top=.82, bottom=.17, left=.18, right=.94)
    stats = indicators['occupancy_statistics']
    publisher.save(fig, 'acumulacion_intersecciones', rows, dict(title='Acumulación observada en intersecciones', objective='Acumulación en intersecciones',
        unit='ocupación media de vehículos', filters=indicators['definitions']['intersection_occupancy'], denominators=stats,
        calculation='sum(occupancy_vehicles * interval_overlap_seconds)/3600; sólo horas completamente cubiertas sin solapamientos',
        observations=stats['source_intervals'], exclusions=stats['missing_or_partial_intersection_hours'],
        source_names=['supplemental_occupancy', 'supplemental_indicator_manifest'], coverage=indicators['coverage'],
        measurement_contract=indicators['comparison_contract']))


def render_spatial(bundle, publisher):
    pending = {
        'corridor_flow': {'status': 'pending', 'required_source': 'Cruces de vehículos con timestamp, sección dirigida y registro de cobertura; definición de secciones ligada al hash de la red. Deduplicar vehículo por sección y franja.',
                          'reason': 'No hay tabla publicada de conteos por sección dirigida. Totales de entradas/transferencias de reservas no equivalen a ese flujo.'},
        'intersection_accumulation': {'status': 'pending', 'required_source': 'Serie de ocupación o cola por intersección y timestamp, con unidades, ámbito corporal y cobertura definidos.',
                                     'reason': 'El resumen nativo sólo conserva agregados globales; WAIT cuenta intentos y no mide longitud de cola.'},
    }
    indicators = bundle.get('indicators', {})
    if indicators.get('ab_definition'):
        bundle = dict(bundle, ab_definition=indicators['ab_definition'])
    if not bundle.get('network_path') or not bundle.get('trips_path'):
        pending['ab'] = {'status': 'pending', 'reason': 'Falta red o tabla de viajes verificada.'}
    elif bundle.get('ab_definition'):
        pending['ab'] = render_ab(bundle, publisher)
    else:
        pending['ab'] = render_candidates(bundle, publisher)
    figures = []
    if pending['ab']['status'] == 'candidates_published':
        figures.append('candidatos_ab')
    elif pending['ab']['status'] == 'published':
        figures.append('tiempo_ab_por_hora')
    if indicators.get('section_hour'):
        render_sections(bundle, publisher);figures.append('flujo_secciones');pending.pop('corridor_flow')
    if indicators.get('occupancy_hour'):
        render_intersections(bundle, publisher);figures.append('acumulacion_intersecciones');pending.pop('intersection_accumulation')
    return {'figures': figures, 'pending': [dict(indicator=name, **record) for name, record in pending.items()
                                          if record['status'] in ('pending', 'candidates_published')]}
