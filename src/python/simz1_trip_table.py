"""Canonical event-leg tables. Streaming CSV, independent of scores and replay."""
import csv
import gzip
import json
import math
from collections import Counter
from contextlib import closing
from pathlib import Path
import tempfile
import os
import xml.etree.ElementTree as ET
from simz1_trip_audit import TripAudit

SCHEMA_VERSION = 1
UNIT = 'departure_arrival_leg'
COLUMNS = ['run_id','iteration','person_id','vehicle_id','trip_index','mode','profile',
           'departure','arrival','duration_seconds','status','abort','departure_link','arrival_link','unit','vehicle_ids']
DEFINITION = ('One row per accepted PersonDepartureEvent; trip_index is its 1-based ordinal for that person '
              'within the iteration, across all modes. Duration = PersonArrivalEvent.time - departure.time '
              'in absolute seconds, including queue and traffic-entry waits. Not door-to-door multimodal trips. '
              'Aborted/censored legs have no arrival or duration. No observations derived from scores.')


def event_trips(path, audit):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rb') as stream:
        context = ET.iterparse(stream,events=('start','end'))
        _,root = next(context)
        if root.tag != 'events': raise ValueError('Se esperaba <events>')
        for action,element in context:
            if action != 'end' or element.tag != 'event': continue
            trip = audit.consume(element.attrib)
            if trip is not None: yield trip
            element.clear();root.clear()
    yield from audit.unfinished()


def table_row(trip, run_id, iteration, profiles):
    vehicles = trip['vehicles']
    return dict(run_id=run_id,iteration=iteration,person_id=trip['person'],
        vehicle_id=vehicles[0] if vehicles else None,vehicle_ids=json.dumps(vehicles,separators=(',',':')),
        trip_index=trip['index'],mode=trip['mode'],profile=profiles.get(trip['person'],'unknown'),
        departure=trip['departure'],arrival=trip['arrival'],
        duration_seconds=trip['arrival']-trip['departure'] if trip['arrival'] is not None else None,
        status=trip['status'],abort=trip['abort'],departure_link=trip.get('departure_link'),
        arrival_link=trip.get('arrival_link'),unit=UNIT)


def rows(path):
    with gzip.open(path,'rt',encoding='utf-8',newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS: raise ValueError(f'Esquema de viajes incompatible: {path}')
        for raw in reader:
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError('Fila CSV con numero de columnas incompatible')
            row = dict(raw)
            for key in ('iteration','trip_index'): row[key] = int(row[key])
            for key in ('departure','arrival','duration_seconds','abort'):
                row[key] = float(row[key]) if row[key] != '' else None
                if row[key] is not None and not math.isfinite(row[key]): raise ValueError(f'Tiempo no finito: {key}')
            if row['departure'] is None or row['departure'] < 0 or row['trip_index'] < 1:
                raise ValueError('Salida o indice invalido')
            if row['unit'] != UNIT or row['status'] not in ('completed','aborted','censored'):
                raise ValueError('Unidad o estado desconocido')
            if not row['person_id'] or not row['mode'] or not row['profile']: raise ValueError('Identidad/modo/perfil ausente')
            if row['status'] == 'completed':
                if (row['arrival'] is None or row['duration_seconds'] is None or row['abort'] is not None or
                    row['arrival'] < row['departure'] or not math.isclose(row['arrival']-row['departure'],row['duration_seconds'],abs_tol=1e-8)):
                    raise ValueError('Duracion incoherente con departure/arrival')
            elif row['arrival'] is not None or row['duration_seconds'] is not None:
                raise ValueError('Viaje incompleto con llegada/duracion inventada')
            if row['abort'] is not None and row['abort'] < row['departure']: raise ValueError('Aborto anterior a departure')
            vehicles = json.loads(row['vehicle_ids'])
            if not isinstance(vehicles,list) or any(not isinstance(v,str) or not v for v in vehicles): raise ValueError('Vehiculos invalidos')
            if row['vehicle_id'] != (vehicles[0] if vehicles else ''): raise ValueError('Identidad de vehiculo incompatible')
            yield row


def validate_compact(path, run_id, iteration, persons=None, horizon=None, *, fixed_day=False):
    counts, indices = Counter(), {}
    with closing(rows(path)) as source:
        for row in source:
            if row['run_id'] != run_id or row['iteration'] != iteration: raise ValueError('CSV de otra corrida/iteracion')
            person = row['person_id']
            if persons is not None and person not in persons: raise ValueError('Persona de CSV ajena a los planes')
            if row['trip_index'] != indices.get(person,0)+1: raise ValueError('Clave de viaje duplicada o indice discontinuo')
            indices[person] = row['trip_index']
            if row['status'] == 'aborted' and (row['abort'] is None or horizon is not None and
                    (row['abort'] > horizon if fixed_day else row['abort'] >= horizon)):
                raise ValueError('Aborto incompatible con el horizonte')
            if fixed_day and horizon is not None and (row['departure'] > horizon or
                    row['arrival'] is not None and row['arrival'] > horizon):
                raise ValueError('Evento fisico despues del corte diario')
            if row['status'] == 'censored' and row['abort'] is not None and horizon is not None and row['abort'] < horizon:
                raise ValueError('Censura oculta un aborto anterior al horizonte')
            counts[row['status']] += 1;counts['rows'] += 1
    return dict(rows=counts['rows'],completed=counts['completed'],aborted=counts['aborted'],censored=counts['censored'],persons=len(indices))


def write_events(events, destination, run_id, iteration, profiles, horizon=None, *, fixed_day=False):
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    audit = TripAudit(horizon, fixed_day=fixed_day)
    fd,temporary = tempfile.mkstemp(dir=destination.parent,suffix='.csv.gz.tmp');os.close(fd)
    try:
        with gzip.open(temporary,'wt',encoding='utf-8',newline='') as stream, closing(event_trips(events,audit)) as trips:
            writer = csv.DictWriter(stream,fieldnames=COLUMNS);writer.writeheader()
            for trip in trips: writer.writerow(table_row(trip,run_id,iteration,profiles))
        os.replace(temporary,destination)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return audit.summary()


def iteration_selection(selection, iteration):
    from simz1_run import checked_path
    if iteration not in selection['manifest']['iterations']['completed']: raise ValueError(f'Iteracion no completada: {iteration}')
    result = selection['manifest']['results'].get(str(iteration))
    chosen = {k:v for k,v in selection.items() if k not in ('events','plans','network')}
    chosen['iteration'] = iteration
    if result:
        chosen.update({name:checked_path(selection['directory'],result[name]) for name in ('events','plans','network')})
    return chosen


def inventory(selection):
    manifest,directory = selection['manifest'],selection['directory']
    report = []
    for iteration in manifest['iterations']['completed']:
        product = manifest.get('trip_products',{}).get(str(iteration),{})
        folder = directory/'output/ITERS'/f'it.{iteration}'
        report.append(dict(iteration=iteration,
            source='native_compact' if 'compact' in product else 'events' if str(iteration) in manifest['results'] else None,
            native_legs_present=(folder/f'{iteration}.legs.csv.gz').is_file(),
            native_trips_present=(folder/f'{iteration}.trips.csv.gz').is_file(),
            events_present=(folder/f'{iteration}.events.xml.gz').is_file(),
            plans_present=(folder/f'{iteration}.plans.xml.gz').is_file(),
            events_validated=str(iteration) in manifest['results'],
            compact_validated='compact' in product,
            note='Native legs/trips are inventoried, but lack terminal status and cannot certify completeness by themselves.'))
    return report


def reusable_table(destination, expected, horizon):
    """Return provenance only after checking identity, sources, bytes and rows.

    This validates the small canonical stream; it never replays XML events or
    Motion_Plan segments. An old v1 sidecar is accepted when its complete source
    records and metric definition still match and the rows satisfy the horizon.
    """
    from simz1_run import sha256
    destination = Path(destination)
    provenance = destination.with_suffix('.provenance.json')
    if not destination.is_file() or not provenance.is_file():
        return None
    try:
        report = json.loads(provenance.read_text(encoding='utf-8'))
        if not isinstance(report, dict) or any(report.get(key) != value for key, value in expected.items()):
            return None
        if report.get('time_horizon_seconds', horizon) != horizon or report.get('csv_sha256') != sha256(destination):
            return None
        counts = validate_compact(destination, expected['run_id'], expected['iteration'], horizon=horizon,
            fixed_day=expected.get('observation_policy')=='fixed-day-24h-v1')
        observed = report.get('observed', {})
        reported = observed.get('counts')
        if reported is None:
            reported = {key: observed.get(name) for key, name in (
                ('rows', 'departures'), ('completed', 'completed_trips'),
                ('aborted', 'aborted_before_horizon'), ('censored', 'pending_trips_at_horizon'))}
        if any(reported.get(key) != counts[key] for key in ('rows', 'completed', 'aborted', 'censored')):
            return None
        return report
    except (OSError, ValueError, TypeError, AttributeError, EOFError):
        # A missing, stale or damaged derived table is recreated from the
        # independently fingerprinted source. Native outputs are never edited.
        return None


def _copy_table(source, destination):
    """Copy compressed bytes atomically, with bounded memory."""
    import shutil
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix='.tmp');os.close(fd)
    try:
        shutil.copyfile(source, temporary);os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def export_table(selection, destination=None):
    from simz1_run import atomic_json,checked_path,sha256
    from procesar_eventos_z1 import read_profiles
    directory,manifest,iteration = selection['directory'],selection['manifest'],selection['iteration']
    destination = Path(destination or directory/'analysis'/f'it.{iteration}'/'trips.csv.gz')
    if not destination.name.endswith('.csv.gz'): raise ValueError('La tabla requiere extension .csv.gz')
    if any(destination.resolve().is_relative_to((directory/name).resolve()) for name in ('output','inputs')):
        raise ValueError('La exportacion no puede sobrescribir entradas ni resultados nativos de la corrida')
    product = manifest.get('trip_products',{}).get(str(iteration),{})
    horizon = manifest['time_horizon']['end_seconds']
    from simz1_day_observation import enabled
    fixed_day = enabled(manifest)
    source_kind = 'native_compact' if 'compact' in product else 'events'
    if 'compact' in product:
        source = checked_path(directory,product['compact'])
        summary_path = checked_path(directory,product['summary'])
        if destination.resolve() == source.resolve(): raise ValueError('No se sobrescribe la fuente nativa')
        sources = product
    elif 'events' in selection:
        sources = manifest['results'][str(iteration)]
        for name in ('events', 'plans'):
            if checked_path(directory, sources[name]) != Path(selection[name]).resolve():
                raise ValueError('Fuente seleccionada ajena a la corrida/iteracion')
        if destination.resolve() in (selection['events'].resolve(),selection['plans'].resolve()): raise ValueError('Salida sobre fuente')
    else:
        raise ValueError(f'Iteracion {iteration} sin eventos validados ni tabla compacta con estado; no se infieren viajes de scores/legs')
    expected = dict(schema_version=SCHEMA_VERSION,run_id=manifest['run_id'],iteration=iteration,
                    definition=DEFINITION,source_kind=source_kind,sources=sources,
                    units='seconds, absolute simulation time; no modulo 24')
    if fixed_day:expected['observation_policy']='fixed-day-24h-v1'
    cached = reusable_table(destination, expected, horizon)
    if cached is not None:
        return destination, cached
    canonical = directory/'analysis'/f'it.{iteration}'/'trips.csv.gz'
    if destination.resolve() != canonical.resolve():
        cached = reusable_table(canonical, expected, horizon)
        if cached is not None:
            _copy_table(canonical, destination)
            atomic_json(destination.with_suffix('.provenance.json'), cached)
            return destination, cached
    if 'compact' in product:
        counts = validate_compact(source,manifest['run_id'],iteration,horizon=horizon,fixed_day=fixed_day)
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        _copy_table(source, destination)
        stats = dict(summary,counts=counts)
    else:
        stats = write_events(selection['events'],destination,manifest['run_id'],iteration,
                             read_profiles(selection['plans']),horizon,fixed_day=fixed_day)
    report = dict(**expected,time_horizon_seconds=horizon,
        vehicle_semantics='vehicle_id is first observed vehicle; vehicle_ids lists all observed vehicles of the leg',
        csv_sha256=sha256(destination),observed=stats)
    atomic_json(destination.with_suffix('.provenance.json'),report)
    return destination,report
