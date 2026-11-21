#!/usr/bin/env python3
r"""Diagnóstico de SOLO LECTURA para SimZ1 220k, sin abrir eventos XML/GZ ni ejecutar MATSim.

Ejemplo (desde raiz del repositorio):
  .\.venv\Scripts\python.exe -B diagnostico_simz1_220k.py

Crea UN reporte local fuera de la corrida, en runtime/diagnostics/analisis-local-220k/.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

DEFAULT_RUN_ID = 'run-z1-1it-cc6bd5666aff46a49456ccd5161cfd85'
PROGRESS_RE = re.compile(r'SIMZ1_PROGRESS simulatedTime=([\d.eE+-]+) \{([^}]*)\}')
TRANSIT_RE = re.compile(r'SIMZ1_TRANSIT_COUNTERS simulatedTime=([\d.eE+-]+) \{([^}]*)\}')


def fields(raw):
    return dict(piece.split('=', 1) for piece in raw.split(', ') if '=' in piece)


def number(text, default=None):
    if text is None:
        return default
    try:
        v = float(text)
        return v if math.isfinite(v) else default
    except (ValueError, TypeError):
        return default


def read_json(path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_network(path):
    if not path.is_file():
        return {}, {'available': False}
    root = ET.parse(path).getroot()
    links = {}
    adj, rev = defaultdict(list), defaultdict(list)
    for link in root.findall('links/link'):
        if 'car' not in {x.strip() for x in link.get('modes', 'car').split(',')}:
            continue
        lid = link.get('id')
        length = number(link.get('length'))
        lanes = number(link.get('permlanes'), 1.0)
        if length is None or lanes is None:
            continue
        meta = {e.get('name'):e.text for e in link.findall('attributes/attribute')}
        start,end=link.get('from'),link.get('to')
        links[lid] = {'length_m': length, 'lanes': lanes,
                      'start_node':start, 'end_node':end,
                      'road_name': meta.get('osm:name'),
                      'osm_way': meta.get('osm:id', meta.get('osm:way_id')),
                      'highway': meta.get('osm:highway')}
        adj[start].append(end);rev[end].append(start)
    # SCC dirigido principal: replica el criterio espacial del generador de red.
    vertices=set(adj)|set(rev); visited=set(); order=[]
    for node in sorted(vertices):
        if node in visited: continue
        stack=[(node,False)]
        while stack:
            current,finish=stack.pop()
            if finish:order.append(current);continue
            if current in visited:continue
            visited.add(current);stack.append((current,True))
            stack.extend((next_node,False) for next_node in adj[current] if next_node not in visited)
    visited=set();scc=[]
    for node in reversed(order):
        if node in visited:continue
        group=set(); stack=[node]
        while stack:
            current=stack.pop()
            if current in visited:continue
            visited.add(current);group.add(current)
            stack.extend(rev[current])
        scc.append(group)
    scc.sort(key=lambda g:(-len(g),min(g)))
    core=scc[0] if scc else set()
    for lid,link in links.items():
        link['eligible_core']=(link['start_node'] in core and link['end_node'] in core)
    core_links=[x for x in links.values() if x['eligible_core']]
    lane_km=sum(x['length_m']*x['lanes'] for x in core_links)/1000
    return links, {'available': True, 'car_links':len(links),
                   'core_nodes':len(core), 'core_links':len(core_links),
                   'core_lane_km':round(lane_km, 3),
                   'core_links_lt_10m':sum(x['length_m'] < 10 for x in core_links)}


def load_progress(log):
    rows = []
    transit = []
    if not log.is_file():
        return rows, transit
    # Unica lectura SECUENCIAL del log textual, NO del XML de eventos.
    with log.open('r',encoding='utf-8',errors='replace') as f:
        for line in f:
            m = PROGRESS_RE.search(line)
            if m:
                x = fields(m.group(2));t = number(m.group(1))
                if t is None:
                    continue
                rows.append(dict(time_s=t, active=number(x.get('activeVehicles')),
                                 arrivals=number(x.get('arrivals'),0),
                                 transitions=number(x.get('linkTransitions'),0),
                                 wait_storage=number(x.get('waitStorage'),0),
                                 wait_signal=number(x.get('waitSignal'),0),
                                 wait_priority=number(x.get('waitPriority'),0),
                                 forced_moves=number(x.get('forcedMoves'),0),
                                 stuck_removals=number(x.get('storageStuckRemovals'),0),
                                 elapsed_s=number(x.get('elapsedSimSeconds'), 60)))
            else:
                m = TRANSIT_RE.search(line)
                if m:
                    x = fields(m.group(2));t=number(m.group(1))
                    if t is not None:
                        transit.append({'time_s':t,
                            'active_public':number(x.get('activePublicVehiclesInDomain')),
                            'expedition_starts':number(x.get('observedExpeditionStarts')),
                            'public_aborts':number(x.get('publicVehicleAbortEvents'))})
    return rows, transit


def hourly_summary(rows, departures):
    grouped = defaultdict(list)
    for row in rows:
        t = row['time_s']
        if t <= 0 or t > 86401:
            continue
        hour = min(23, int(math.floor((t-1e-6)/3600)))
        grouped[hour].append(row)
    result = []
    for h in range(24):
        rr = grouped.get(h, [])
        planned = departures.get(f'{h:02d}:00') if departures else None
        result.append({'hour':f'{h:02d}:00',
            'planned_private_departures':int(planned) if planned is not None else None,
            'native_arrivals_all_families':int(sum(x['arrivals'] or 0 for x in rr)) if rr else None,
            'native_transitions':int(sum(x['transitions'] or 0 for x in rr)) if rr else None,
            'active_at_last_observation':int(rr[-1]['active']) if rr and rr[-1]['active'] is not None else None,
            'minutes_observed':round(sum(x['elapsed_s'] or 0 for x in rr)/60,2),
            'wait_storage_attempts':int(sum(x['wait_storage'] or 0 for x in rr)) if rr else None,
            'wait_signal_attempts':int(sum(x['wait_signal'] or 0 for x in rr)) if rr else None})
    return result


def origin_metrics(report, links):
    by_link = report.get('first_origins_by_link', {}) if isinstance(report,dict) else {}
    origin_count = sum(by_link.values()) if by_link else 0
    bins = []
    for threshold in (2.1, 4.5, 8, 10, 20):
        origin = sum(n for lid,n in by_link.items()
                     if lid in links and links[lid]['length_m']<threshold)
        total_lane_m = sum(x['length_m']*x['lanes'] for x in links.values() if x['eligible_core'])
        tiny_lane_m = sum(x['length_m']*x['lanes'] for x in links.values() if x['eligible_core'] and x['length_m'] < threshold)
        bins.append({'threshold_m':threshold,
                     'origin_count_lt_m':origin if origin_count else None,
                     'origin_pct_lt_m':round(100*origin/origin_count,2) if origin_count else None,
                     'network_lane_length_pct_lt_m':round(100*tiny_lane_m/total_lane_m,2) if total_lane_m else None})
    top = []
    for lid,n in sorted(by_link.items(), key=lambda x:(-x[1],x[0]))[:20]:
        link=links.get(lid, {})
        top.append({'link_id':lid,'origin_count':n, **link})
    return {'first_origin_count_reported':origin_count, 'thresholds':bins,
            'top_20_first_origin_links':top,
            'not_measured':'La distribucion de origenes NO demuestra por si sola un defecto fisico o un atasco.'}


def available_run_diagnostics(repo, run):
    index=read_json(repo/'runtime/diagnostics/masiva-220k-20261031/220-latest.json') or {}
    directory=Path(index['directory']) if index.get('directory') else None
    found=[]
    if directory and directory.is_dir():
        for sub in ('monitor','status'):
            folder=directory/sub
            if not folder.is_dir():continue
            for file in sorted(folder.rglob('*')):
                if file.is_file() and file.suffix.lower() in ('.json','.csv','.md'):
                    found.append(dict(path=str(file),bytes=file.stat().st_size))
    return {'stage_dir':str(directory) if directory else None,
            'run_matches_index':str(run) == str((index.get('run_directory') or '')),
            'files_count':len(found),'first_30_files':found[:30]}


def render_md(summary, hourly, origin, transit):
    lines=['# SimZ1 220K — diagnostico local de solo lectura',
           '',f"Run ID: `{summary.get('run_id') or 'no identificado'}`",
           f"Run directory: `{summary['run_directory']}`",
           f"Estado del manifiesto: `{summary.get('status')}`; validacion: `{summary.get('validation')}`",
           '', '## Progreso horario (NO son conteos de personas unicas en cada contador de espera)',
           '', '|Hora|Salidas privadas previstas|Llegadas nativas (todas las familias)|Transiciones|Activos ultimo registro|Min observados|Intentos storage|',
           '|---|---:|---:|---:|---:|---:|---:|']
    def n(v):return '—' if v is None else f'{v:,}'
    for r in hourly:
        if r['minutes_observed'] == 0 and r['planned_private_departures'] is None:
            continue
        lines.append('|'+r['hour']+'|'+n(r['planned_private_departures'])+'|'+n(r['native_arrivals_all_families'])+'|'+n(r['native_transitions'])+'|'+n(r['active_at_last_observation'])+'|'+str(r['minutes_observed'])+'|'+n(r['wait_storage_attempts'])+'|')
    lines += ['', '## Origenes sobre enlaces muy cortos', '',
              f"Total de primeros origenes en reporte: {n(origin['first_origin_count_reported'])}",
              '|Enlace mas corto que|Primeros origenes|% de origenes|% metros-carril de red|',
              '|---|---:|---:|---:|']
    for a in origin['thresholds']:
        lines.append('|'+str(a['threshold_m'])+' m|'+n(a['origin_count_lt_m'])+'|'+n(a['origin_pct_lt_m'])+'|'+n(a['network_lane_length_pct_lt_m'])+'|')
    lines += ['', '## Indicadores de autobuses', '']
    if transit:
        first,last=transit[0],transit[-1]
        lines += [f"Ultima observacion a {last['time_s']/3600:.2f} h: {n(last['active_public'])} buses activos; {n(last['expedition_starts'])} salidas de expediciones observadas; {n(last['public_aborts'])} abortos reportados."]
    else:
        lines += ['No hay registros de diagnostico de buses en el log consultado.']
    lines += ['', '## Diagnosticos ya guardados de esta corrida', '',
              f"Stage: `{summary['stage_diagnostics'].get('stage_dir')}`",
              f"Archivos JSON/CSV/MD de monitor/status: {summary['stage_diagnostics']['files_count']}",
              '', '## Interpretacion y limites', '',
              '1. Los origenes en enlaces cortos y el volumen horario son condiciones de la demanda; no prueban un error del motor.',
              '2. `arrivals` es un contador nativo global por intervalo, no solo de particulares. Las salidas previstas son particulares.',
              '3. `wait_storage_attempts` suma intentos, NO vehiculos distintos.',
              '4. La hora del registro corresponde al FIN del intervalo; al agrupar se asigna a la hora en que ocurrio la mayor parte del intervalo.',
              '5. Este diagnostico NO lee events.xml.gz ni determina por si solo el primer corredor bloqueado.',
              '6. Si aparece flujo casi cero, hay que observar primeras colas, receptores y dependencias entre 05:30 y 08:30; no asumir una causa sin evidencia.',
              '7. No cambiar ni matar procesos de la corrida activa ni el codigo bajo pruebas.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    repo=args.repo.resolve()
    run=(args.run_dir or repo/'scenarios/zona1/montecarlo'/DEFAULT_RUN_ID).resolve()
    out=(args.out or repo/'runtime/diagnostics/analisis-local-220k').resolve()
    if not run.is_dir():
        parser.error(f'No se encontro la corrida: {run}')
    if out == run or run in out.parents:
        parser.error('Los resultados deben quedar FUERA de la carpeta de corrida activa')
    report=read_json(run/'montecarlo-report.json') or {}
    manifest=read_json(run/'run-manifest.json') or {}
    links,net=load_network(repo/'scenarios/zona1/network.xml')
    progress,transit=load_progress(run/'matsim-run.log')
    departures=report.get('departures_by_hour',{})
    hourly=hourly_summary(progress,departures)
    origin=origin_metrics(report,links)
    validation=manifest.get('validation') or {}
    summary={'generated_at_local':datetime.now().isoformat(),
             'run_directory':str(run), 'run_id':manifest.get('run_id'),
             'status':manifest.get('status'), 'phase':manifest.get('phase'),
             'validation':validation.get('status') if isinstance(validation,dict) else validation,
             'current_progress_time_s':progress[-1]['time_s'] if progress else None,
             'observations':len(progress),
             'source_report_present':bool(report), 'native_log_present':(run/'matsim-run.log').is_file(),
             'origin_policy':report.get('origin_policy'),
             'destination_policy':report.get('destination_policy'),
             'od_mode':(report.get('spatial_demand') or {}).get('mode','network_or_unreported'),
             'network':net, 'origin':origin,
             'stage_diagnostics':available_run_diagnostics(repo,run),
             'last_transit':transit[-1] if transit else None,
             'hypotheses_to_check':['Sobreconcentracion de origenes en enlaces cortos',
                                     'Demanda privada OD dentro de red en lugar de viajes de paso',
                                     'Ciclo de almacenamiento/FIFO/prioridad que detiene descargas',
                                     'Capacidad insuficiente de algunos accesos/salidas en hora pico'],
             'warning':'Estas son hipotesis. Este programa no diagnostica una causa raiz sin los snapshots de enlaces/cabezas.'}
    out.mkdir(parents=True,exist_ok=True)
    with (out/'horas.csv').open('w', newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(hourly[0]));writer.writeheader();writer.writerows(hourly)
    (out/'diagnostico.json').write_text(json.dumps({'summary':summary,'hourly':hourly},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (out/'RESUMEN.md').write_text(render_md(summary,hourly,origin,transit),encoding='utf-8')
    print('DIAGNOSTICO LOCAL (sin ejecutar MATSim ni abrir eventos XML/GZ)')
    print('run_id:',summary['run_id'],'status:',summary['status'],'validation:',summary['validation'])
    print('simulated_h:',None if not progress else round(progress[-1]['time_s']/3600,3))
    print('ORIGENES <10 m:',origin['thresholds'][3])
    print('ULTIMAS HORAS OBSERVADAS:')
    for row in [r for r in hourly if r['minutes_observed']>0][-8:]:
        print(row['hour'], 'previstas',row['planned_private_departures'],
              'llegadas',row['native_arrivals_all_families'],
              'transiciones',row['native_transitions'],
              'activos',row['active_at_last_observation'])
    print('REPORTE:',out/'RESUMEN.md')
    print('JSON:',out/'diagnostico.json')
    print('CSV:',out/'horas.csv')
    return 0

if __name__=='__main__':sys.exit(main())
