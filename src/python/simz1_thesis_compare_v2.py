"""Comparación descriptiva v8 con censos publicados; nunca ejecuta MATSim.

python python/simz1_thesis_compare_v2.py --output graficas_tesis_v2/comparacion-1k-vs-10k-v8
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from simz1_thesis import (Publisher, compatibility, csv_rows, load_bundle, read_json,
                          safe_output, sha, style, verified, write_json)

ROOT = Path(__file__).resolve().parents[1]
RUNS = [ROOT/'scenarios/zona1/montecarlo'/('run-bg1-a32f15487b1a49ac910ba799175658ca'),
        ROOT/'scenarios/zona1/montecarlo'/('run-bg10-e496c091b9ef46ee9ca381576135e299')]
VERSION = 'simz1-thesis-compare-v2.0'
GROUPS = ['carro', 'moto', 'pesado', 'transmetro', 'tubus']
LABELS = dict(carro='Carros', moto='Motos', pesado='Camiones', transmetro='Transmetro', tubus='TuBus',
              nonpublic='No públicos', public='Buses', all='Toda la red')
COLORS = ['#0072b2', '#d55e00']
RUN_LABELS = ['Run1000', 'Run10K']


def family(row):
    f = row['family']
    if f != 'bus':
        if f not in GROUPS:
            raise ValueError('Familia desconocida: '+str(f))
        return f
    identifier = str(row['trip_id'])
    if identifier.startswith('bus:transmetro_'): return 'transmetro'
    if identifier.startswith('bus:tubus_'): return 'tubus'
    raise ValueError('Expedición sin sistema público identificable: '+identifier)


def statistics(values):
    values = np.asarray(list(values), dtype=float)
    if len(values) == 0:
        return dict(n=0, mean_minutes=None, median_minutes=None, p90_minutes=None, p95_minutes=None)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError('Duración negativa/no finita')
    return dict(n=len(values), mean_minutes=float(values.mean()/60),
                median_minutes=float(np.quantile(values, .5)/60),
                p90_minutes=float(np.quantile(values, .9)/60), p95_minutes=float(np.quantile(values, .95)/60))


def observed_hour(value):
    if value is None:return None
    if not 0<=value<=86400:raise ValueError('Evento fuera de jornada observada')
    return min(23,int(value//3600))


def select_flow_sections(tables,names,limit=4):
    """One observed section per named street, never sum serial link counts."""
    common=set(tables[0])&set(tables[1])
    ranked=sorted(common,key=lambda link:(-(tables[0][link]['entries']+tables[1][link]['entries']),link))
    result=[];seen_names=set()
    for link in ranked:
        name=(names.get(link) or '').strip()
        if not name or name.casefold() in seen_names:continue
        seen_names.add(name.casefold());result.append(link)
        if len(result)==limit:break
    if len(result)<limit:raise ValueError('No hay suficientes vías nombradas comunes para secciones')
    return result


def active_metrics(intervals, horizon=86400):
    """Counts physical IDs, checks overlap and integrates [entry, exit)."""
    by_vehicle = defaultdict(list)
    for vid, start, end in intervals:
        if not (0 <= start <= end <= horizon): raise ValueError('Intervalo fuera del horizonte')
        by_vehicle[vid].append((start, end))
    events = defaultdict(int)
    hours = [0.0]*24
    for vid, ranges in by_vehicle.items():
        previous_end = None
        for start, end in sorted(ranges):
            if previous_end is not None and start < previous_end:
                raise ValueError('Intervalos solapados para vehículo físico '+vid)
            previous_end = end
            if start == end: continue
            events[start] += 1
            events[end] -= 1
            for hour in range(int(start//3600), min(23, int(math.nextafter(end, -math.inf)//3600))+1):
                hours[hour] += max(0.0, min(end, (hour+1)*3600)-max(start, hour*3600))/3600
    current = peak = 0
    peak_time = None
    for instant, delta in sorted(events.items()):
        current += delta
        if current < 0: raise ValueError('Ocupación negativa')
        if current > peak: peak, peak_time = current, instant
    if current: raise ValueError('Intervalos no cerrados al horizonte')
    return dict(peak_active=peak, peak_time_seconds=peak_time,
                mean_active=sum(hours)/24, mean_by_hour=hours,
                physical_vehicles_observed=len(by_vehicle))


def read_lifecycle(bundle):
    directory = bundle['run_dir']/'analysis/it.0/balanced-launch'
    digest = bundle['balanced_report']['files']['day-lifecycle.csv']
    path = verified(directory, dict(path='day-lifecycle.csv', sha256=digest))
    rows = csv_rows(path)
    expected = bundle['balanced_report']['day_observation']
    if len(rows) != expected['scheduled_trips'] or Counter(r['status'] for r in rows) != Counter(expected['counts']):
        raise ValueError('Lifecycle no concilia con censo nativo')
    seen = set()
    for row in rows:
        if row['run_id'] != bundle['identity']['run_id'] or row['iteration'] != 0:
            raise ValueError('Lifecycle de otra corrida/iteración')
        if row['trip_id'] in seen: raise ValueError('Trip ID duplicado')
        seen.add(row['trip_id'])
        row['group'] = family(row)
        if row['status'] == 'completed':
            if row['arrival'] is None or row['departure'] is None or row['complete_duration_seconds'] is None:
                raise ValueError('Completado sin duración/tiempos')
            if not math.isclose(row['complete_duration_seconds'], row['arrival']-row['departure'], abs_tol=1e-6):
                raise ValueError('Duración no coincide con salida/llegada')
        elif row['complete_duration_seconds'] is not None:
            raise ValueError('No completado contiene duración completa')
    bundle['sources'].append(dict(path=str(path), sha256=digest, bytes=path.stat().st_size,
                                  kind='day_lifecycle', verification='balanced report SHA256; identity/counts/durations reconciled'))
    return rows


def summarize(bundle, rows, label):
    result = dict(bundle=bundle, rows=rows, label=label, stats=[], activity={}, hourly=[])
    for group in GROUPS+['nonpublic','public','all']:
        selected = [r for r in rows if group == 'all' or r['group'] == group or
                    (group == 'nonpublic' and r['family'] != 'bus') or
                    (group == 'public' and r['family'] == 'bus')]
        complete = [r for r in selected if r['status'] == 'completed']
        entry = [r for r in selected if r['traffic_entry'] is not None]
        stat = dict(run=label, run_id=bundle['identity']['run_id'], iteration=0, group=group,
                    scheduled=len(selected), completed=len(complete),
                    not_started=sum(r['status']=='scheduled_not_departed' for r in selected),
                    active_at_cut=sum(r['status']=='active_at_cut' for r in selected),
                    waiting_at_cut=sum(r['status']=='waiting_for_incorporation' for r in selected),
                    prior_aborts=sum(r['abort_before_cleanup'] is not None for r in selected),
                    **statistics(r['complete_duration_seconds'] for r in complete))
        wait = statistics(r['incorporation_delay_seconds'] for r in entry if r['incorporation_delay_seconds'] is not None)
        stat.update({'entry_wait_'+k:v for k,v in wait.items()})
        intervals = []
        for row in entry:
            end = row['traffic_exit']
            if end is None:
                end = row['observed_traffic_end_seconds']
            if end is None: raise ValueError('Entrada sin fin observado/corte')
            intervals.append((row['vehicle_id'], row['traffic_entry'], end))
        activity = active_metrics(intervals)
        result['activity'][group] = activity
        stat.update({k:v for k,v in activity.items() if k != 'mean_by_hour'})
        result['stats'].append(stat)
        for hour in range(24):
            selected_hour = [r for r in selected if observed_hour(r['departure'])==hour]
            result['hourly'].append(dict(run=label,group=group,hour=hour,
                departures=len(selected_hour), arrivals=sum(observed_hour(r['arrival'])==hour for r in selected),
                mean_active=activity['mean_by_hour'][hour],
                **statistics(r['complete_duration_seconds'] for r in selected_hour if r['status']=='completed')))
    return result


def heading(fig, title, note=''):
    fig.suptitle(title, fontsize=16, fontweight='semibold', y=.99)
    fig.text(.5,.91,'Run1000 vs Run10K · v8 · iteración 0 · horizonte 00:00–24:00',ha='center',fontsize=10,color='#475569')
    if note: fig.text(.04,.018,note,fontsize=9,color='#475569',va='bottom')
    fig.tight_layout(rect=(.02,.085,.99,.86))


def time_axis(ax, ylabel):
    ax.set(xlim=(0,24),ylim=(0,None),xlabel='Hora simulada',ylabel=ylabel)
    ax.set_xticks(range(0,25,4),[f'{h:02d}:00' for h in range(0,25,4)])
    ax.grid(axis='y',alpha=.2)


def save(pub, fig, stem, rows, title, calculation, limitation, units, objective='OE2 y OE3; objetivo general para duraciones', **extra):
    meta = dict(title=title, objective=objective, variable=title, units=units,
        calculation=calculation, interpretation='Comparación descriptiva de estas dos realizaciones aceptadas; sin inferencia causal ni calibración.',
        limitations=limitation, utility='Evaluar cambios observados entre cargas y sustentar resultados con denominadores explícitos.',
        filters='Run IDs explícitos, iteración 0, censo completo 0–86400 s.',
        denominators='N=1000/10000 corresponde a privados+carga; flota pública fija 269, oferta fija 13261 expediciones.',
        observations=len(rows), exclusions='Duraciones sólo completados; censurados/no iniciados conservados en tablas de completitud.')
    meta.update(extra)
    pub.save(fig,stem,rows,meta)


def render_core(summaries,pub):
    stats=[r for s in summaries for r in s['stats']]
    hourly=[r for s in summaries for r in s['hourly']]
    fig,axs=plt.subplots(2,2,figsize=(13,8))
    for ax,field,title in zip(axs.flat,['mean_minutes','median_minutes','p90_minutes','p95_minutes'],['Media','Mediana','Percentil 90','Percentil 95']):
        for j,s in enumerate(summaries):
            vals=[next(r[field] for r in s['stats'] if r['group']==g) for g in GROUPS]
            ax.bar(np.arange(5)+(j-.5)*.34,vals,.34,label=s['label'],color=COLORS[j])
        ax.set_xticks(range(5),[LABELS[g] for g in GROUPS]);ax.set_ylabel('Duración completa (min)');ax.set_title(title);ax.grid(axis='y',alpha=.2)
    axs[0,0].legend()
    heading(fig,'Tiempos de viaje por tipo de vehículo','Solicitud/salida → llegada; sólo completados. Buses: expediciones, con paradas. Censura privada: 2 en 1K y 200 en 10K.')
    save(pub,fig,'comparacion_tiempos_por_tipo',stats,'Media, mediana, p90 y p95 por tipo',
         'Estadísticas por viaje/expedición completado de complete_duration_seconds; cuantiles lineales numpy.',
         'Excluye censura; mezcla OD y horas distintos dentro de cada tipo. Buses no equivalen a viajes de pasajeros.', 'minutos')

    fig,axs=plt.subplots(2,3,figsize=(14,8))
    ecdf=[]
    for ax,g in zip(axs.flat,GROUPS):
        for j,s in enumerate(summaries):
            values=sorted(r['complete_duration_seconds']/60 for r in s['rows'] if r['group']==g and r['status']=='completed')
            y=np.arange(1,len(values)+1)/len(values)
            ax.step(values,y,where='post',color=COLORS[j],label=f"{s['label']} (n={len(values):,})")
            ecdf.extend(dict(run=s['label'],group=g,duration_minutes=v,cumulative_fraction=float(p)) for v,p in zip(values,y))
        ax.set(title=LABELS[g],xlabel='Duración completa (min)',ylabel='Fracción acumulada',ylim=(0,1.02));ax.legend(fontsize=8);ax.grid(alpha=.2)
    axs.flat[-1].axis('off')
    axs.flat[-1].text(.05,.8,'Cada escalón es un viaje completo.\n\nLas curvas conservan las colas largas.\nLa censura se informa por separado.\n\nNo se imputan llegadas al corte.',va='top',fontsize=11)
    heading(fig,'Distribución acumulada de tiempos','Cada tipo usa su propio eje horizontal para conservar resolución; comparar 1K/10K dentro del mismo panel.')
    save(pub,fig,'comparacion_distribuciones_tiempos',ecdf,'Distribuciones empíricas acumuladas',
         'ECDF = rango/n, con una observación por viaje o expedición completado.',
         'No representa la distribución completa de los censurados; no estima tiempos contrafactuales.', 'minutos y fracción')

    fig,axs=plt.subplots(2,2,figsize=(13,8))
    for i,g in enumerate(['nonpublic','public']):
        for k,field in enumerate(['departures','arrivals']):
            ax=axs[i,k]
            for j,s in enumerate(summaries):
                rows=[r for r in s['hourly'] if r['group']==g]
                ax.step([r['hour'] for r in rows]+[24],[r[field] for r in rows]+[rows[-1][field]],where='post',color=COLORS[j],label=s['label'])
            ax.set_title(LABELS[g]+' · '+('salidas/inicios' if k==0 else 'llegadas'));time_axis(ax,'Viajes o expediciones / hora');ax.legend()
    heading(fig,'Salidas y llegadas por hora','Intervalos [h,h+1); última hora incluye el corte. Salida observada no equivale siempre a incorporación ni a hora programada.')
    save(pub,fig,'comparacion_salidas_llegadas_hora',hourly,'Salidas y llegadas horarias',
         'Conteo separado por departure y arrival del lifecycle, horarios absolutos [h,h+1); última hora incluye 86400 s.',
         'Las llegadas de una hora pueden proceder de salidas de horas anteriores. No es flujo de una sección vial.', 'viajes o expediciones/hora')

    fig,axs=plt.subplots(1,2,figsize=(13,5.5))
    groups=GROUPS+['all']
    for j,s in enumerate(summaries):
        vals=[s['activity'][g]['peak_active'] for g in groups]
        bars=axs[0].bar(np.arange(len(groups))+(j-.5)*.34,vals,.34,label=s['label'],color=COLORS[j])
        axs[0].bar_label(bars,fontsize=8,padding=3)
        rows=[r for r in s['hourly'] if r['group']=='all']
        axs[1].step([r['hour'] for r in rows]+[24],[r['mean_active'] for r in rows]+[rows[-1]['mean_active']],where='post',color=COLORS[j],label=s['label'])
    axs[0].set_xticks(range(len(groups)),[LABELS[g] for g in groups],rotation=20,ha='right');axs[0].set_ylabel('Vehículos simultáneos (máximo)');axs[0].set_ylim(top=axs[0].get_ylim()[1]*1.13);axs[0].legend();axs[0].grid(axis='y',alpha=.2)
    time_axis(axs[1],'Vehículos activos (media temporal)');axs[1].legend()
    heading(fig,'Activos máximos y acumulación global','Máximos calculados en tiempos nativos de entrada/salida; el máximo total no es la suma de máximos por tipo.')
    save(pub,fig,'comparacion_activos_maximos',stats+hourly,'Activos máximos e integral horaria',
         'Barrido de intervalos [traffic_entry,traffic_exit) por ID físico; activos al corte cierran a 86400 sólo para integrar. Media=vehículo-segundos/3600.',
         'Activos de toda la red; no longitud de cola ni ocupación de una intersección. No incluye espera exterior de incorporación.', 'vehículos')

    fig,axs=plt.subplots(1,2,figsize=(12,5.5));comp=[]
    for j,s in enumerate(summaries):
        counts=s['bundle']['identity']['counts'];n=counts['non_public_vehicles_configured']
        for k,g in enumerate(GROUPS[:3]):
            value=sum(r['group']==g for r in s['rows']);comp.append(dict(run=s['label'],category=g,physical_configured=value,nonpublic_share_percent=100*value/n))
            axs[0].bar(k+(j-.5)*.34,value,.34,color=COLORS[j],label=s['label'] if k==0 else None)
        fleets=[len({r['vehicle_id'] for r in s['rows'] if r['group']==g}) for g in GROUPS[3:]]
        axs[1].bar(np.arange(2)+(j-.5)*.34,fleets,.34,color=COLORS[j],label=s['label'])
        comp.extend(dict(run=s['label'],category=g,physical_configured=v,nonpublic_share_percent=None) for g,v in zip(GROUPS[3:],fleets))
    axs[0].set_xticks(range(3),[LABELS[g] for g in GROUPS[:3]]);axs[0].set_ylabel('Vehículos no públicos configurados');axs[0].legend()
    axs[1].set_xticks(range(2),[LABELS[g] for g in GROUPS[3:]]);axs[1].set_ylabel('Buses físicos con oferta programada');axs[1].legend()
    heading(fig,'Composición de tráfico y flota pública','Carros 44%, motos 55%, camiones 1% del N no público. La flota pública y su oferta no crecen diez veces.')
    save(pub,fig,'comparacion_composicion_trafico',comp,'Composición física configurada',
         'Privados/carga: una fila de censo por vehículo. Buses: IDs físicos distintos con expediciones programadas.',
         'Composición configurada no equivale a composición simultánea del tráfico ni proporción de expediciones.', 'vehículos y % del N no público')

    fig,axs=plt.subplots(1,2,figsize=(12,5.7));busrows=[]
    for ax,g in zip(axs,GROUPS[3:]):
        for j,s in enumerate(summaries):
            stat=next(r for r in s['stats'] if r['group']==g);started=stat['scheduled']-stat['not_started']
            row=dict(run=s['label'],system=g,scheduled=stat['scheduled'],started=started,completed=stat['completed'],not_started=stat['not_started'],completion_percent=100*stat['completed']/stat['scheduled']);busrows.append(row)
            bars=ax.bar(np.arange(3)+(j-.5)*.34,[row[k] for k in ['scheduled','started','completed']],.34,color=COLORS[j],label=s['label']);ax.bar_label(bars,padding=3,fontsize=8)
        ax.set_xticks(range(3),['Programadas','Iniciadas','Completadas']);ax.set_title(LABELS[g]);ax.set_ylabel('Expediciones');ax.legend();ax.set_ylim(top=ax.get_ylim()[1]*1.12)
    heading(fig,'Transporte público: oferta y ejecución','269 buses físicos y 13 261 expediciones programadas en cada corrida. No iniciado no se clasifica como viaje censurado en tráfico.')
    save(pub,fig,'comparacion_transporte_publico',busrows,'Transporte público programado/iniciado/completado',
         'Conteos de expediciones por prefijo de trip_id: transmetro_ y tubus_. Observado = departure existente; completo = censo completed.',
         'No hay ocupación de pasajeros; no se infiere utilización comercial. Cambios en horarios/offsets deben consultarse en compatibilidad.', 'expediciones')

    fig,axs=plt.subplots(1,2,figsize=(12,5.7));effect=[]
    for j,s in enumerate(summaries):
        stat=next(r for r in s['stats'] if r['group']=='nonpublic')
        fields=['completed','active_at_cut','waiting_at_cut'];values=[100*stat[k]/stat['scheduled'] for k in fields]
        bars=axs[0].bar(np.arange(3)+(j-.5)*.34,values,.34,label=s['label'],color=COLORS[j]);axs[0].bar_label(bars,fmt='%.2f',padding=3,fontsize=8)
        for g in GROUPS[:3]:
            st=next(r for r in s['stats'] if r['group']==g)
            effect.append(dict(st,completion_percent=100*st['completed']/st['scheduled']))
        vals=[next(r['entry_wait_mean_minutes'] for r in s['stats'] if r['group']==g) for g in GROUPS[:3]]
        bars=axs[1].bar(np.arange(3)+(j-.5)*.34,vals,.34,color=COLORS[j],label=s['label']);axs[1].bar_label(bars,fmt='%.2f',padding=3,fontsize=8)
    axs[0].set_xticks(range(3),['Completados','Activos al corte','Esperando entrada'],rotation=10);axs[0].set(ylabel='% de privados + carga programados',ylim=(0,112));axs[0].legend()
    axs[1].set_xticks(range(3),[LABELS[g] for g in GROUPS[:3]]);axs[1].set_ylabel('Espera media de incorporación (min)');axs[1].legend();axs[1].set_ylim(top=max(.1,axs[1].get_ylim()[1]*1.15))
    heading(fig,'Carga observada: completitud y espera de entrada','Espera sólo para quienes se incorporaron; quienes siguen esperando al corte se cuentan por separado. Cero abortos previos.')
    save(pub,fig,'comparacion_carga_espera_censura',effect,'Completitud, censura y espera de incorporación',
         'Estados del censo precleanup / N no público. Media de incorporation_delay_seconds sólo cuando hubo entrada.',
         'Espera observada de incorporados es selectiva; omite duración final desconocida de quienes siguen esperando. Comparación descriptiva, sin réplicas.', 'porcentaje y minutos')

    fig,axs=plt.subplots(2,3,figsize=(14,8))
    for ax,g in zip(axs.flat,GROUPS):
        for j,s in enumerate(summaries):
            rows=[r for r in s['hourly'] if r['group']==g]
            ax.plot([r['hour']+.5 for r in rows],[np.nan if r['mean_minutes'] is None else r['mean_minutes'] for r in rows],color=COLORS[j],label=s['label']+' media')
            ax.plot([r['hour']+.5 for r in rows],[np.nan if r['median_minutes'] is None else r['median_minutes'] for r in rows],color=COLORS[j],linestyle=':',label=s['label']+' mediana')
        ax.set_title(LABELS[g]);time_axis(ax,'Duración completa (min)')
    axs.flat[-1].axis('off');axs.flat[-1].legend(*axs.flat[0].get_legend_handles_labels(),loc='center')
    heading(fig,'Tiempo de viaje según hora de salida','Cohortes por salida/inicio observado. Ausencia de muestra produce un hueco; el CSV conserva n por hora y tipo.')
    save(pub,fig,'comparacion_tiempos_por_hora',hourly,'Media y mediana por hora y tipo',
         'Estadísticas individuales de completados agrupados por floor(departure/3600); no promedios de medias.',
         'Horas con muestras pequeñas son inestables; la censura puede sesgar horas finales. No incluye no iniciados.', 'minutos')

    decomposition=[];fig,axs=plt.subplots(1,2,figsize=(13,5.8),sharey=True)
    for ax,j,s in zip(axs,range(2),summaries):
        wait=[];traffic=[]
        for g in GROUPS:
            rows=[r for r in s['rows'] if r['group']==g and r['status']=='completed']
            if any(r['traffic_entry'] is None for r in rows): raise ValueError('Completado sin entrada para descomposición')
            entry_wait=float(np.mean([r['traffic_entry']-r['departure'] for r in rows])/60)
            after_entry=float(np.mean([r['arrival']-r['traffic_entry'] for r in rows])/60)
            wait.append(entry_wait);traffic.append(after_entry)
            decomposition.append(dict(run=s['label'],group=g,n=len(rows),entry_wait_mean_minutes=entry_wait,
                after_entry_mean_minutes=after_entry,total_mean_minutes=entry_wait+after_entry))
        ax.bar(range(5),traffic,color=COLORS[j],label='Entrada a tráfico → llegada')
        ax.bar(range(5),wait,bottom=traffic,color=COLORS[j],alpha=.35,hatch='//',label='Salida/solicitud → entrada')
        ax.set_xticks(range(5),[LABELS[g] for g in GROUPS],rotation=15);ax.set_ylabel('Duración media de completados (min)');ax.set_title(s['label']);ax.legend(fontsize=8);ax.grid(axis='y',alpha=.2)
    heading(fig,'Separar espera de incorporación y tiempo en tráfico','Misma cohorte completa para ambos componentes; entrada → llegada incluye paradas y detenciones durante el recorrido.')
    save(pub,fig,'comparacion_descomposicion_tiempos',decomposition,'Componentes observados del tiempo completo',
         'Por completado: espera=traffic_entry−departure; después de entrada=arrival−traffic_entry. Promedios sobre la misma muestra; suma exacta igual a tiempo completo.',
         'No aísla demora semafórica ni tiempo en movimiento. No incluye espera de buses antes del inicio efectivo de su expedición.', 'minutos')


def compatibility_record(bundles):
    try:
        contract=compatibility(bundles)
        contract['strict_comparability']='passed'
    except ValueError as error:
        contract=dict(strict_comparability='not_equivalent_under_existing_contract',reason=str(error),
            interpretation='Comparación descriptiva autorizada entre las dos corridas explícitas; no experimento causal aislando N. Se preserva el rechazo del comparador estricto.',
            identities=[b['identity'] for b in bundles])
    contract['configured_n_definition']='Privados y carga; excluye flota pública'
    contract['censoring_rule']='Duraciones sólo completed del censo precleanup; active_at_cut y waiting_for_incorporation no reciben llegada imputada.'
    contract['replicates_per_scale']=1
    contract['inputs']={b['identity']['run_id']:{k:v for k,v in b['manifest'].get('inputs',{}).items() if any(t in k.lower() for t in ['network','signal','transit','freight'])} for b in bundles}
    audit_path=ROOT/'graficas_tesis_v2/auditoria-existente.json'
    if audit_path.is_file():
        audit=read_json(audit_path)
        contract['semantic_audit']=audit.get('comparability',{})
        contract['semantic_audit_source']=dict(path=str(audit_path),sha256=sha(audit_path))
        contract['semantic_interpretation']='El inventario compara completos los horarios: las diferencias de bytes están en metadatos de N y su política; la oferta de rutas, salidas y flota permanece equivalente. Se conserva el rechazo estricto por hash; dos realizaciones no permiten inferencia causal.'
    return contract


def generate(output=ROOT/'graficas_tesis_v2/comparacion-1k-vs-10k-v8', spatial_dir=None, maps_dir=None):
    bundles=[load_bundle(p,0) for p in RUNS]
    output=safe_output(output,bundles)
    summaries=[summarize(b,read_lifecycle(b),label) for b,label in zip(bundles,RUN_LABELS)]
    contract=compatibility_record(bundles)
    style()
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.compare-stage-',dir=output.parent) as temporary:
        stage=Path(temporary)/'published'
        pub=Publisher(stage,[b['identity'] for b in bundles],[s for b in bundles for s in b['sources']],dict(comparison=VERSION))
        render_core(summaries,pub)
        render_ab_comparison(summaries,pub,Path(maps_dir) if maps_dir else ROOT/'graficas_tesis_v2/mapas-red-vial')
        if spatial_dir:
            render_spatial_comparison(summaries,pub,Path(spatial_dir))
        else:
            pub.pending.append('Flujo de secciones y acumulación crítica requieren tablas espaciales adicionales verificadas; no se sustituyen por WAIT.')
        write_json(stage/'compatibility.json',contract)
        manifest=pub.finish()
        manifest['schema_version']=VERSION
        manifest['compatibility']=contract
        manifest['source_verification']='Published lifecycle and analysis artifacts verified by their native-bound reports. Spatial figures consume verified compact CSVs from the separately identified replay extractor; this comparison script reads no events or replay SQLite and performs no native validation.'
        write_json(stage/'figures-manifest.json',manifest)
        write_json(stage/'manifest.json',manifest)
        lines=['# Comparación Run1000 vs Run10K v8','',
            'Iteración 0; horizonte completo 0–86400 s. Identidades y fuentes verificadas antes de leer los censos publicados. No se leen eventos ni se ejecuta simulación.','',
            '**Interpretación:** comparación descriptiva, una realización por carga. N representa privados + carga; flota de 269 buses y 13 261 expediciones programadas en ambas corridas. No equivale a aumentar toda la demanda por diez ni acredita calibración.','',
            '**Censura:** duración completa sólo si el censo registra `completed`. Esperar incorporación no es circular. Abortos administrativos finales no son abortos previos.','',
            '**Compatibilidad:** '+contract['strict_comparability']+'. '+contract.get('reason','Se cumplieron los controles del comparador existente.')+' Véase [compatibility.json](compatibility.json).','',
            contract.get('semantic_interpretation',''),'',
            '| Figura | Qué muestra y cálculo | Objetivo | Limitaciones |','|---|---|---|---|']
        for record in pub.figures:
            stem=record['stem'];data=read_json(stage/(stem+'.json'))['metadata']
            lines.append(f"| [{data['title']}]({stem}.png) · [SVG]({stem}.svg) · [CSV]({stem}.csv) · [JSON]({stem}.json) | {data['calculation']} | {data['objective']} | {data['limitations']} |")
        if pub.pending: lines+=['','## Cobertura pendiente','']+['- '+str(p) for p in pub.pending]
        (stage/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        output.mkdir(parents=True,exist_ok=True)
        for path in stage.iterdir(): shutil.copy2(path,output/path.name)
    return manifest


def render_ab_comparison(summaries,pub,directory):
    candidates_path=directory/'ab-candidatos.csv';observations_path=directory/'ab-observaciones.csv'
    if not candidates_path.is_file() or not observations_path.is_file():
        pub.pending.append('A–B común: faltan tablas de selección y observaciones del generador de mapas.')
        return
    candidates=csv_rows(candidates_path);observations=csv_rows(observations_path)
    identities={s['bundle']['identity']['run_id'] for s in summaries}
    if any(r['run_id'] not in identities or r['iteration']!=0 for r in observations):
        raise ValueError('Observación A–B de otra corrida/iteración')
    for path in [candidates_path,observations_path]:
        pub.sources.append(dict(path=str(path),sha256=sha(path),bytes=path.stat().st_size,
            kind='observed_ab_table',verification='Map selection from verified trips.csv.gz; each duration/identity checked and reconciled to lifecycle'))
    rows=[]
    for c in candidates:
        for index,s in enumerate(summaries):
            rid=s['bundle']['identity']['run_id']
            selected=[r for r in observations if r['candidate']==c['candidate'] and r['run_id']==rid]
            expected=c['n_run1000' if index==0 else 'n_run10000']
            if len(selected)!=expected: raise ValueError('Muestra A–B no concilia con selección')
            lifecycle={r['vehicle_id']:r for r in s['rows'] if r['family']!='bus'}
            for r in selected:
                native=lifecycle[r['vehicle_id']]
                if native['status']!='completed' or native['departure']!=r['departure_seconds'] or native['arrival']!=r['arrival_seconds']:
                    raise ValueError('Observación A–B no coincide con lifecycle')
                if r['duration_seconds']!=r['arrival_seconds']-r['departure_seconds']:
                    raise ValueError('Duración A–B no coincide con extremos')
                if (r['origin_link'],r['destination_link'])!=(c['origin_link'],c['destination_link']):
                    raise ValueError('Par A–B contradictorio')
            censored_declared=0
            for r in s['rows']:
                if r['family']=='bus' or r['status'] not in ('active_at_cut','waiting_for_incorporation') or not r.get('od'):continue
                od=json.loads(r['od'])
                for entry in od.values():
                    if (entry.get('origin_link'),entry.get('destination_link'))==(c['origin_link'],c['destination_link']):
                        censored_declared+=1
            rows.append(dict(candidate=c['candidate'],run=s['label'],run_id=rid,
                origin_link=c['origin_link'],destination_link=c['destination_link'],
                declared_od_censored=censored_declared,selection_score=c['selection_score'],
                **statistics(r['duration_seconds'] for r in selected)))
    fig,axs=plt.subplots(2,2,figsize=(13,8))
    for ax,c in zip(axs.flat,candidates):
        for j,s in enumerate(summaries):
            row=next(r for r in rows if r['candidate']==c['candidate'] and r['run']==s['label'])
            vals=[row[k] for k in ['mean_minutes','median_minutes','p90_minutes','p95_minutes']]
            ax.bar(np.arange(4)+(j-.5)*.34,vals,.34,label=f"{s['label']} (n={row['n']})",color=COLORS[j])
        ax.set_xticks(range(4),['Media','Mediana','P90','P95']);ax.set_ylabel('Duración completa (min)')
        ax.set_title(f"A–B {c['candidate']} · completados comunes mínimos: {c['selection_score']}");ax.legend(fontsize=8);ax.grid(axis='y',alpha=.2)
    heading(fig,'A–B observados comunes: tiempos exploratorios','Anclas de salida/llegada observadas; tiempo incluye incorporación. Los cuatro pares comparten A; extremos y muestras en CSV/JSON.')
    save(pub,fig,'comparacion_tiempos_ab_observados',rows,'Tiempo entre pares A–B observados comunes',
         'Selección top 4 por min(n completados Run1000,n completados Run10K), desempate lexicográfico; privados z1_ y extremos distintos. Estadísticas de arrival−departure.',
         'Selección posterior a observar datos; no pareja preespecificada ni control OD/hora/tipo. Censura por OD declarado se reporta separada y no prueba llegada observada al B. No mide puerta a puerta fuera de la red.', 'minutos; n de viajes', 'Objetivo general A–B; OE2 y OE3')


def render_spatial_comparison(summaries,pub,directory):
    """Compare fixed sections selected from compact, full-day link tables."""
    tables=[];coverage_records=[]
    for scenario,s in zip(['run1000','run10000'],summaries):
        manifest_path=directory/scenario/'manifest.json'
        summary_path=directory/scenario/'link_summary.csv'
        hourly_path=directory/scenario/'link_hourly.csv'
        if not manifest_path.is_file() or not summary_path.is_file() or not hourly_path.is_file():
            raise ValueError('Paquete espacial incompleto: '+str(summary_path.parent))
        spatial=read_json(manifest_path)
        ident=spatial['identity'];native=s['bundle']['identity'];coverage=spatial['coverage']
        if spatial['status']!='complete' or ident['run_id']!=native['run_id'] or ident['iteration']!=0 or ident['run_manifest_sha256']!=native['manifest_sha256']:
            raise ValueError('Identidad/estado espacial incompatible')
        if not coverage['complete_native_scan'] or coverage['segments_read']!=coverage['expected_segments']:
            raise ValueError('Cobertura espacial incompleta')
        totals=spatial['totals']
        if totals['unassociated_vehicle_seconds']!=0 or totals['associated_vehicle_seconds']!=totals['native_vehicle_seconds']:
            raise ValueError('Falta asociación durante intervalos: requiere comparación explícitamente parcial')
        coverage_records.append(dict(run=s['label'],coverage=coverage,totals=totals,
            interpretation='Integrales completas en [0,86400); el estado puntual al corte se conserva separado, incluidas asociaciones ausentes.'))
        outputs={str(Path(r['path']).resolve()):r for r in spatial['outputs']}
        for path in [summary_path,hourly_path]:
            record=outputs.get(str(path.resolve()))
            if record is None or record['sha256']!=sha(path) or record['bytes']!=path.stat().st_size:
                raise ValueError('Hash/tamaño de exportación espacial incompatible: '+str(path))
        rows=csv_rows(summary_path)
        if len({r['link_id'] for r in rows})!=len(rows):raise ValueError('Resumen espacial duplica enlaces')
        table={r['link_id']:r for r in rows}
        for row in rows:
            if row['coverage_seconds']!=86400:raise ValueError('Cobertura espacial no es jornada completa')
            if any(row[k]<0 for k in ['entries','traffic_entries','vehicle_seconds','peak_active']):raise ValueError('Medición espacial negativa')
        tables.append(table)
        for path in [summary_path,hourly_path]:
            pub.sources.append(dict(path=str(path),sha256=sha(path),bytes=path.stat().st_size,
                kind='native_link_association_aggregate',verification='Full-day compact export from coordinated native interval extractor; coverage and selection checked'))
        pub.sources.append(dict(path=str(manifest_path),sha256=sha(manifest_path),bytes=manifest_path.stat().st_size,
            kind='native_spatial_export_manifest',verification='native manifest SHA, exact Run ID/iteration, complete native segment scan and output hashes'))
    links_path=ROOT/'graficas_tesis_v2/mapas-red-vial/network-links.csv'
    names={r['link_id']:r.get('osm_name') for r in csv_rows(links_path)} if links_path.is_file() else {}
    if links_path.is_file():
        pub.sources.append(dict(path=str(links_path),sha256=sha(links_path),bytes=links_path.stat().st_size,
            kind='simulated_network_link_names',verification='Map export of simulated network; labels only'))
    common=set(tables[0])&set(tables[1])
    selected={}
    for kind,field in [('secciones','entries'),('puntos-criticos','vehicle_seconds')]:
        selected[kind]=(select_flow_sections(tables,names) if kind=='secciones' else
            sorted(common,key=lambda link:(-(tables[0][link][field]+tables[1][link][field]),link))[:4])
        table_rows=[]
        for rank,link in enumerate(selected[kind],1):
            table_rows.append(dict(rank=rank,section=('S' if kind=='secciones' else 'C')+str(rank),
                link_id=link,name=names.get(link),selection_metric=field,
                value_run1000=tables[0][link][field],value_run10000=tables[1][link][field],
                selection_score=tables[0][link][field]+tables[1][link][field]))
        with (pub.directory/(kind+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(table_rows[0]));writer.writeheader();writer.writerows(table_rows)
        selection=('Orden pooled entries descendente y link_id ascendente; conservar primer enlace de cada osm_name no vacío distinto hasta cuatro secciones. Sin suma de enlaces de calle.' if kind=='secciones' else
            'Top4 por suma de vehículo-segundos entre corridas; desempate link_id; mismos enlaces en ambas.')
        write_json(pub.directory/(kind+'.json'),dict(selection=selection,rows=table_rows))
    wanted=set(selected['secciones']+selected['puntos-criticos']);hourly=[]
    for scenario,s in zip(['run1000','run10000'],summaries):
        with (directory/scenario/'link_hourly.csv').open(encoding='utf-8-sig',newline='') as stream:
            for raw in csv.DictReader(stream):
                if raw['link_id'] not in wanted:continue
                row={k:(v if k=='link_id' else float(v)) for k,v in raw.items()}
                row['hour']=int(row['hour']);row['run']=s['label'];row['run_id']=s['bundle']['identity']['run_id'];row['iteration']=0
                if row['coverage_seconds']!=3600:raise ValueError('Intervalo espacial incompleto')
                if not math.isclose(row['mean_active'],row['vehicle_seconds']/3600,abs_tol=1e-8):raise ValueError('Media espacial no concilia con integral')
                hourly.append(row)
        for link in wanted:
            seen=[r['hour'] for r in hourly if r['run']==s['label'] and r['link_id']==link]
            if sorted(seen)!=list(range(24)):raise ValueError('Faltan/duplican horas de sección: '+link)
    for kind,field,stem,title,ylabel in [
        ('secciones','entries','comparacion_flujo_secciones','Flujo en cuatro secciones fijas comunes','Entradas LinkEnter / hora'),
        ('puntos-criticos','mean_active','comparacion_acumulacion_critica','Acumulación en cuatro enlaces críticos','Activos asociados (vehículos)')]:
        fig,axs=plt.subplots(2,2,figsize=(13,8));rows=[]
        for rank,(ax,link) in enumerate(zip(axs.flat,selected[kind]),1):
            for j,s in enumerate(summaries):
                observed=sorted([r for r in hourly if r['run']==s['label'] and r['link_id']==link],key=lambda r:r['hour'])
                rows.extend(dict(r,section=('S' if kind=='secciones' else 'C')+str(rank),name=names.get(link)) for r in observed)
                ax.step([r['hour'] for r in observed]+[24],[r[field] for r in observed]+[observed[-1][field]],where='post',label=s['label'],color=COLORS[j])
            name=names.get(link)
            ax.set_title(f"{('S' if kind=='secciones' else 'C')+str(rank)} · "+(name if name else link),fontsize=10)
            time_axis(ax,ylabel);ax.legend(fontsize=8)
        heading(fig,title,'Enlaces idénticos; selección exploratoria por suma entre corridas. Integrales [0,24h) completas; 14 asociaciones ausentes sólo al corte 10K.')
        calculation=('Conteos LinkEnter por enlace/hora. Orden por suma diaria entre corridas y desempate ID; primer enlace por osm_name no vacío distinto, hasta cuatro vías. VehicleEntersTraffic separado, sin sumarlo al aforo.' if kind=='secciones' else
            'Integral de asociación nativa [entrada,salida) al enlace / 3600; top4 enlaces por suma diaria de vehículo-segundos entre corridas, desempate ID.')
        limitation=('Aforo de enlace/sección candidata: pasos, no necesariamente vehículos distintos ni flujo total de una calle. No se suman enlaces sucesivos como si fueran un único aforo.' if kind=='secciones' else
            'Proxy de acumulación en enlace, no longitud de cola ni espera semafórica; no reconstruye posiciones corporales. Enlaces paralelos no prueban independencia espacial.')
        limitation+=' En 10K faltan 14 asociaciones puntuales exactamente a 86400 s; no hay vehículo-segundos sin asociar en [0,86400).'
        save(pub,fig,stem,rows,title,calculation,limitation,ylabel,'OE2 y OE3: flujo y acumulación',coverage_by_run=coverage_records)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'graficas_tesis_v2/comparacion-1k-vs-10k-v8')
    parser.add_argument('--spatial-dir',type=Path)
    parser.add_argument('--maps-dir',type=Path)
    args=parser.parse_args(argv)
    manifest=generate(args.output,args.spatial_dir,args.maps_dir)
    print(json.dumps(dict(status='generated',figures=len(manifest['figures']),output=str(args.output)),ensure_ascii=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
