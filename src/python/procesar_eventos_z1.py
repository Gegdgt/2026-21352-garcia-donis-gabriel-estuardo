"""Consolida departure/arrival de MATSim en CSV.gz; Excel es opcional y acotado.

Agent_ID es el ID person del evento, no un vehicle ID. Los viajes sin llegada
se conservan con Arrival_Time y Travel_Time_Minutes vacios, nunca como cero.
Se leen todas las horas y todos los agentes, sin filtro 09:00-15:00 ni muestreo.
"""
import argparse
import gzip
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


from simz1_event_validation import unfinished_counts

PROJECT = Path(__file__).resolve().parents[1]
COLUMNS = ['Agent_ID', 'Departure_Time', 'Arrival_Time', 'Travel_Time_Minutes', 'Hour_Block',
           'Trip_ID', 'Trip_Index', 'Status', 'Censored', 'Departure_Seconds', 'Arrival_Seconds', 'Abort_Seconds']


def movement_end_time(start, end, length, freespeed, *, vehicle_speed=None, tolerance=2):
    """Estimated motion followed by residual time of unknown cause.

    Both limits are required to infer a wait. Missing vehicle data must not
    manufacture a queue. Absolute event endpoints remain untouched.
    """
    if not all(math.isfinite(v) for v in (start, end, length)) or end < start or length < 0:
        raise ValueError('Invalid link interval or length')
    for speed in (freespeed, vehicle_speed):
        if speed is not None and (not math.isfinite(speed) or speed <= 0):
            raise ValueError('Speed limit must be positive and finite')
    if end == start or freespeed is None or vehicle_speed is None:
        return end
    free_flow_time = length / min(freespeed, vehicle_speed)
    # QSim rounding can add a second per lane: do not display it as a queue.
    if end - start <= free_flow_time + tolerance:
        return end
    return start + free_flow_time


def clock(seconds):
    """Hora simulada, preservando dias como horas >=24 y fracciones de segundo."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60
    value = f'{remaining:09.6f}'.rstrip('0').rstrip('.')
    if remaining < 10 and not value.startswith('0'):
        value = '0' + value
    return f'{hours:02}:{minutes:02}:{value}'


def trip_row(person, departure, arrival=None):
    hour = int(departure // 3600)
    return [person, clock(departure), clock(arrival) if arrival is not None else None,
            (arrival-departure)/60 if arrival is not None else math.nan,
            f'{hour:02}:00-{hour+1:02}:00']


def read_profiles(plans_path):
    """Mapea person ID a perfil sin retener el XML completo de planes."""
    profiles = {}
    opener = gzip.open if str(plans_path).endswith('.gz') else open
    with opener(plans_path, 'rb') as stream:
        context=ET.iterparse(stream, events=('start','end'))
        _,root=next(context)
        for action,element in context:
            if action=='end' and element.tag=='person':
                value=element.findtext("attributes/attribute[@name='drivingProfile']", default='unknown')
                profiles[element.get('id')]=value
                element.clear(); root.clear()
    return profiles


def read_person_metadata(plans_path):
    """Read recorded identities without using speeds, IDs or MATSim mode as a type.

    Only one XML person is retained at a time. The returned identity index is
    keyed by person_id, never vehicle_id. Native transit drivers are not in this
    demand population and must not be synthesized from a name prefix.
    """
    from simz1_agent_types import CANONICAL_TYPES, SCHEMA_VERSION
    from simz1_road_catalog import IDENTITIES, SCHEMA as ROAD_SCHEMA
    from simz1_run import xml_elements
    metadata = {}
    legacy = {'Normal', 'Tortuga', 'Liebre'}
    for person in xml_elements(plans_path, 'person', 'population'):
        ident = person.get('id')
        if not ident or ident in metadata:
            raise ValueError('Persona sin ID o duplicada en metadatos de planes')
        attrs = {a.get('name'): (a.text or '').strip() for a in person.findall('attributes/attribute')}
        schema, agent = attrs.get('simz1AgentSchema'), attrs.get('simz1AgentType')
        effective, driving = attrs.get('effectiveVehicleType'), attrs.get('drivingProfile')
        family, profile, label, role, source = 'unknown', 'unknown', 'Sin identidad', 'unknown', 'unresolved'
        if attrs.get('simz1FreightService') == 'simz1-freight-weekday-v1':
            if agent != 'TransportePesado' or effective != 'FreightTruck' or driving != 'TransportePesado':
                raise ValueError('Freight identity mismatch: '+ident)
            family, profile, label, role, source = 'pesado', 'TransportePesado', 'Transporte pesado', 'service_driver', 'recorded_freight_service'
        elif schema == ROAD_SCHEMA:
            if agent not in IDENTITIES or effective != agent:
                raise ValueError(f'Tipo efectivo inconsistente en planes: {ident}')
            family, expected_driving, label = IDENTITIES[effective]
            if attrs.get('simz1VehicleFamily') != family or driving != expected_driving:
                raise ValueError(f'Familia/perfil inconsistente con tipo efectivo: {ident}')
            profile, role, source = effective, 'driver', 'recorded_road_schema'
        elif schema == SCHEMA_VERSION:
            if agent not in CANONICAL_TYPES:
                raise ValueError(f'Tipo de agente desconocido: {ident}')
            if agent == 'TransportePublico':
                if effective:
                    raise ValueError(f'Pasajero confundido con vehiculo de flota: {ident}')
                family, profile, label, role = 'passenger', agent, 'Pasajero de transporte publico', 'passenger'
            else:
                if effective != agent or driving != agent:
                    raise ValueError(f'Tipo efectivo inconsistente en planes: {ident}')
                family, _, label = IDENTITIES[effective]
                profile, role = effective, 'driver'
            source = 'recorded_six_type_schema'
        elif schema:
            # Future schemas need an explicit interpretation; never guess a moto.
            source = 'unrecognized_schema'
        elif effective:
            if agent and agent != effective:
                raise ValueError(f'Tipo de agente y vehiculo contradictorios: {ident}')
            if effective in IDENTITIES:
                family, expected_driving, label = IDENTITIES[effective]
                if (attrs.get('simz1VehicleFamily', family) != family or
                        driving and driving not in (effective, expected_driving)):
                    raise ValueError(f'Familia/perfil inconsistente con tipo efectivo: {ident}')
                profile, role, source = effective, 'driver', 'recorded_effective_vehicle_type'
            else:
                source = 'unrecognized_effective_vehicle_type'
        elif not agent and driving in legacy:
            family, _, label = IDENTITIES[driving]
            profile, role, source = driving, 'driver', 'historical_driving_profile'
        plans = person.findall('plan')
        selected = [plan for plan in plans if plan.get('selected') == 'yes']
        if len(selected) == 1:
            selected_plan = selected[0]
        elif len(plans) <= 1:
            selected_plan = plans[0] if plans else None
        else:
            raise ValueError(f'Plan seleccionado ambiguo en metadatos: {ident}')
        modes = sorted({leg.get('mode') for leg in selected_plan.findall('leg') if leg.get('mode')}) if selected_plan is not None else []
        metadata[ident] = dict(person_id=ident, profile=profile, label=label, family=family,
            agent_type=agent, effective_vehicle_type=effective, driving_profile=driving,
            agent_schema=schema, planned_modes=modes, population_role=role,
            monte_carlo_eligible=attrs.get('simz1FreightService') != 'simz1-freight-weekday-v1',
            internal_transit_driver=False, identity_source=source)
        cohort = attrs.get('simz1PopulationCohort')
        if cohort is not None:
            if cohort not in ('main', 'warmup_context', 'post_context'):
                raise ValueError(f'Cohorte temporal desconocida: {ident}: {cohort}')
            planned = float(attrs.get('simz1PlannedDepartureSeconds', 'nan'))
            study_start = float(attrs.get('simz1StudyStartSeconds', 'nan'))
            if not math.isfinite(planned) or planned < 0 or not math.isfinite(study_start) or study_start < 0:
                raise ValueError(f'Cohorte sin tiempos absolutos validos: {ident}')
            metadata[ident].update(population_cohort=cohort, planned_departure_seconds=planned,
                                   study_start_seconds=study_start)
    return metadata


def metadata_for_selection(selection):
    """Use fingerprinted iteration plans, or the same run's frozen input plans.

    An iteration may have a validated native compact table without XML plans.
    In that case input attributes identify demand persons; actual MATSim mode
    and vehicle IDs still come from each canonical event-leg row.
    """
    from simz1_run import checked_path
    manifest, directory, iteration = selection['manifest'], selection['directory'], selection['iteration']
    result = manifest.get('results', {}).get(str(iteration), {})
    record = result.get('plans')
    origin = 'iteration_plans'
    if record is None:
        record = manifest.get('inputs', {}).get('plans')
        origin = 'frozen_input_plans'
    if record is None:
        raise ValueError('No hay planes identificados para los metadatos de perfiles')
    path = checked_path(directory, record)
    if 'plans' in selection and origin == 'iteration_plans' and Path(selection['plans']).resolve() != path:
        raise ValueError('Planes seleccionados ajenos a la iteracion validada')
    return read_person_metadata(path), dict(origin=origin, artifact=record,
        actual_mode_source='canonical trip row PersonDepartureEvent.legMode',
        population_scope='persons in fingerprinted plans; native internal transit drivers excluded')


def read_trips(events_path, horizon=None):
    """All trips with per-person IDs, absolute times and explicit censoring."""
    import pandas as pd
    from simz1_trip_audit import TripAudit, row_identity
    audit, rows = TripAudit(horizon), []
    def row(trip):
        return trip_row(trip['person'],trip['departure'],trip['arrival']) + [
            row_identity(trip), trip['index'], trip['status'], trip['censored'],
            trip['departure'], trip['arrival'], trip['abort']]
    with gzip.open(events_path, 'rb') as stream:
        context = ET.iterparse(stream, events=('start','end'))
        _, root = next(context)
        if root.tag != 'events':
            raise ValueError('Se esperaba la raiz <events> de MATSim')
        for action, element in context:
            if action != 'end' or element.tag != 'event':
                continue
            trip = audit.consume(element.attrib)
            if trip is not None:
                rows.append(row(trip))
            element.clear(); root.clear()
    rows.extend(row(trip) for trip in audit.unfinished())
    # Preserve the legacy DataFrame ordering; the compact stream uses terminal order.
    rows.sort(key=lambda value:value[7] != 'completed')
    return pd.DataFrame(rows, columns=COLUMNS), audit.summary()


def export_trips(events_path, output_path, plans_path=None, json_path=None, horizon=None):
    import pandas as pd
    events_path, output_path = Path(events_path), Path(output_path)
    if events_path.resolve() == output_path.resolve():
        raise ValueError('La salida no puede sobrescribir los eventos')
    if output_path.suffix.lower() != '.xlsx':
        raise ValueError('La salida debe tener extension .xlsx')
    frame, stats = read_trips(events_path, horizon)
    profiles=read_profiles(plans_path) if plans_path is not None else {}
    if len(frame) > 1048575:
        raise ValueError('Se excede el limite de filas de una hoja Excel')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.stem + '.tmp.xlsx')
    try:
        with pd.ExcelWriter(temporary, engine='openpyxl') as writer:
            frame.to_excel(writer, sheet_name='Viajes', index=False, freeze_panes=(1, 0))
            sheet = writer.sheets['Viajes']
            sheet.auto_filter.ref = sheet.dimensions
            from openpyxl.utils import get_column_letter
            for i, width in enumerate((26, 22, 22, 24, 22, 32, 12, 14, 14, 22, 22, 22), 1):
                sheet.column_dimensions[get_column_letter(i)].width = width
            # IDs y horas son texto literal, incluso IDs que comienzan con '='.
            for row in sheet.iter_rows(min_row=2):
                for index in (0, 1, 2, 4, 5, 7):
                    if row[index].value is not None:
                        row[index].data_type = 's'
                row[3].number_format = '0.0000'
        temporary.replace(output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if json_path is not None:
        records=frame.astype(object).where(pd.notna(frame), None).to_dict(orient='records')
        for record in records:
            record['Profile']=profiles.get(record['Agent_ID'], 'No disponible')
        Path(json_path).write_text(json.dumps(records,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return stats


def export_selected(selection, output=None, json_path=None, *, excel=None, excel_max_rows=100000):
    from simz1_run import atomic_json
    from simz1_trip_table import export_table, rows, inventory
    if output and Path(output).suffix.lower()=='.xlsx':
        if excel:raise ValueError('Excel indicado dos veces')
        excel,output=Path(output),None
    destination,report=export_table(selection,output)
    atomic_json(selection['directory']/'analysis'/'trip_inventory.json',dict(run_id=selection['manifest']['run_id'],iterations=inventory(selection)))
    if 'events' in selection:
        from simz1_priority_audit import export_selected as export_priority
        export_priority(selection,destination.parent/'tiempos_viaje_zona1.priority.json')
        atomic_json(destination.parent/'tiempos_viaje_zona1.hourly.json',
                    dict(run_id=selection['manifest']['run_id'],iteration=selection['iteration'],
                         generated_departures_by_hour=selection['manifest'].get('generated_departures_by_hour'),
                         temporal_demand=selection['manifest'].get('temporal_demand'),
                         observed=selection['manifest']['results'][str(selection['iteration'])]['temporal_events']))
    if excel: export_bounded_excel(destination,excel,excel_max_rows)
    if json_path:
        with Path(json_path).open('w',encoding='utf-8') as stream:
            stream.write('[')
            for index,row in enumerate(rows(destination)):
                if index:stream.write(',')
                json.dump(row,stream,ensure_ascii=False,allow_nan=False)
            stream.write(']')
    return destination,report


def export_bounded_excel(csv_path, destination, max_rows=100000):
    from simz1_trip_table import rows,COLUMNS as fields
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    if not 1<=max_rows<=1048575:raise ValueError('Limite Excel debe estar entre 1 y 1048575')
    destination=Path(destination)
    if destination.suffix.lower()!='.xlsx':raise ValueError('Excel requiere extension .xlsx')
    # Count first so a rejected request cannot leave a half-written workbook.
    from contextlib import closing
    with closing(rows(csv_path)) as source:
        for count,_ in enumerate(source,1):
            if count>max_rows:raise ValueError(f'Excel excede --excel-max-rows={max_rows}; CSV completo conservado')
    destination.parent.mkdir(parents=True,exist_ok=True)
    book=Workbook(write_only=True);sheet=book.create_sheet('Viajes');sheet.append(fields)
    for row in rows(csv_path):
        cells=[]
        for field in fields:
            cell=WriteOnlyCell(sheet,value=row[field])
            if isinstance(row[field],str):cell.data_type='s'
            cells.append(cell)
        sheet.append(cells)
    temporary=destination.with_suffix('.tmp.xlsx')
    try:book.save(temporary);temporary.replace(destination)
    finally:
        book.close()
        if temporary.exists():temporary.unlink()


def main():
    from simz1_run import select_run
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, help='Carpeta con manifiesto; omitir usa latest-successful')
    parser.add_argument('--iteration', type=int)
    parser.add_argument('--output', type=Path, help='Por defecto: <run>/analysis/it.N/trips.csv.gz; .xlsx solicita Excel explicitamente')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--excel',type=Path,help='Excel opcional, acotado; CSV.gz sigue siendo el producto principal')
    parser.add_argument('--excel-max-rows',type=int,default=100000)
    parser.add_argument('--all-iterations',action='store_true',help='Exporta solo iteraciones con fuentes validas; informa las ausentes')
    args = parser.parse_args()
    try:
        selection=select_run(args.run_dir,args.iteration,require_events=False)
        if args.all_iterations:
            from simz1_trip_table import inventory,iteration_selection,export_table
            if args.output or args.json or args.excel:raise ValueError('--all-iterations usa una carpeta por iteracion; omita --output/--json/--excel')
            for item in inventory(selection):
                if item['source'] and item['iteration']!=selection['iteration']:export_table(iteration_selection(selection,item['iteration']))
                elif not item['source']:print(f"Iteracion {item['iteration']}: sin observaciones de viajes validadas; no se inventan filas")
        output,stats=export_selected(selection,args.output,args.json,excel=args.excel,excel_max_rows=args.excel_max_rows)
    except (OSError, ValueError, ET.ParseError, EOFError, ImportError) as exc:
        parser.exit(1, f'No se pudo exportar: {exc}\n')
    print(json.dumps(dict(output=str(output), **stats), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
