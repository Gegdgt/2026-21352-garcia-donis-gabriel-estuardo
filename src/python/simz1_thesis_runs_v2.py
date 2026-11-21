"""Thesis extensions from verified, already published lifecycle tables only."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
import matplotlib.pyplot as plt
from simz1_thesis import Publisher, load_bundle, sha, style, verified, write_json, generate_individual

ROOT = Path(__file__).resolve().parents[1]
RUNS = [('run1000-v8-a32f15487b1a49ac910ba799175658ca', 'run-bg1-a32f15487b1a49ac910ba799175658ca'),
        ('run10000-v8-e496c091b9ef46ee9ca381576135e299', 'run-bg10-e496c091b9ef46ee9ca381576135e299')]
GROUPS = ('carro', 'moto', 'pesado', 'transmetro', 'tubus')
LABEL = dict(zip(GROUPS, ('Carros', 'Motos', 'Camiones', 'Transmetro', 'TuBus')))
COLOR = dict(zip(GROUPS, ('#0072b2', '#009e73', '#b0792a', '#8064a2', '#cc79a7')))


def lifecycle(bundle):
    report = bundle['balanced_report']; base = bundle['run_dir'] / 'analysis/it.0/balanced-launch'
    path = verified(base, dict(path='day-lifecycle.csv', sha256=report['files']['day-lifecycle.csv']))
    sources = [dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size,
                    kind='complete_lifecycle', verification='balanced report SHA256 and exact row identity')]
    services = {v: s['service_id'] for s in bundle['manifest']['public_transport']['service_counts'] for v in s['configured_vehicle_ids']}
    out = []
    with path.open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['run_id'] != bundle['identity']['run_id'] or int(r['iteration']) != 0:
                raise ValueError('Lifecycle identity mismatch')
            r['service'] = services.get(r['vehicle_id'])
            r['group'] = r['service'].split('_')[0] if r['family'] == 'bus' else r['family']
            if r['group'] not in GROUPS: raise ValueError('Unknown family/service')
            for k in ('scheduled_departure', 'departure', 'traffic_entry', 'traffic_exit', 'arrival', 'abort_before_cleanup', 'complete_duration_seconds', 'incorporation_delay_seconds'):
                r[k] = float(r[k]) if r.get(k) else None
            out.append(r)
    if len({r['trip_id'] for r in out}) != len(out): raise ValueError('Duplicate lifecycle episode')
    return out, sources


def distribution(values):
    a = np.asarray(values, dtype=float)
    if len(a) and (not np.isfinite(a).all() or (a < 0).any()): raise ValueError('Invalid duration')
    return dict(n=len(a), mean_minutes=float(a.mean()) if len(a) else None,
        median_minutes=float(np.quantile(a,.5)) if len(a) else None,
        p90_minutes=float(np.quantile(a,.9)) if len(a) else None,
        p95_minutes=float(np.quantile(a,.95)) if len(a) else None)


def active_metrics(rows, start=0, end=86400):
    """Exact lifecycle stock; half-open physical intervals, simultaneous deltas grouped."""
    deltas = defaultdict(int); seconds = 0.
    physical = defaultdict(list)
    for r in rows:
        a = r['traffic_entry']
        if a is None: continue
        ends = [r[k] for k in ('traffic_exit', 'arrival', 'abort_before_cleanup') if r[k] is not None]
        b = min(ends, default=86400.)
        if b < a: raise ValueError('Negative native traffic interval')
        physical[r['vehicle_id']].append((a,b))
        a,b = max(start,a),min(end,b)
        if b > a: deltas[a] += 1; deltas[b] -= 1; seconds += b-a
    for intervals in physical.values():
        intervals.sort()
        if any(b > c for (a,b),(c,d) in zip(intervals,intervals[1:])): raise ValueError('Overlapping physical vehicle episodes')
    stock=peak=0
    for t in sorted(deltas):
        stock+=deltas[t]; peak=max(peak,stock)
        if stock<0: raise ValueError('Negative stock')
    return dict(peak_active=peak, mean_active=seconds/(end-start), vehicle_seconds=seconds)


def summary(rows):
    result=[]
    for g in GROUPS:
        a=[r for r in rows if r['group']==g]
        d=[r['complete_duration_seconds']/60 for r in a if r['status']=='completed']
        waits=[r['incorporation_delay_seconds']/60 for r in a if r['incorporation_delay_seconds'] is not None]
        states=Counter(r['status'] for r in a)
        result.append(dict(group=g, scheduled=len(a), completed=states['completed'],
            censored=sum(n for s,n in states.items() if s not in ('completed','scheduled_not_departed','aborted_before_cut')),
            not_started=states['scheduled_not_departed'], aborted_before_cut=sum(r['abort_before_cleanup'] is not None for r in a),
            physical_vehicles=len({r['vehicle_id'] for r in a}), **distribution(d), **active_metrics(a),
            wait_mean_minutes=float(np.mean(waits)) if waits else None, wait_n=len(waits)))
    return result


def hour_rows(rows):
    out=[]
    for g in GROUPS:
        a=[r for r in rows if r['group']==g]
        for h in range(24):
            rec=dict(group=g,hour=h)
            for key in ('scheduled_departure','departure','traffic_entry','arrival'):
                rec[key]=sum(r[key] is not None and h*3600<=r[key]<(h+1)*3600 for r in a)
            cohort=[r for r in a if r['departure'] is not None and h*3600<=r['departure']<(h+1)*3600]
            rec.update(distribution([r['complete_duration_seconds']/60 for r in cohort if r['status']=='completed']))
            waits=[r['incorporation_delay_seconds']/60 for r in cohort if r['incorporation_delay_seconds'] is not None]
            rec['wait_mean_minutes']=float(np.mean(waits)) if waits else None
            rec['wait_n']=len(waits)
            rec.update(active_metrics(a,h*3600,(h+1)*3600))
            out.append(rec)
    return out


def render(bundle, destination):
    rows,sources=lifecycle(bundle); totals=summary(rows); hourly=hour_rows(rows)
    pub=Publisher(destination,[bundle['identity']],bundle['sources']+sources,dict(bundle['source_versions'],collection_recipe_sha256=sha(__file__)))
    n=bundle['identity']['N_configured']; notes=[]
    def save(fig,stem,title,data,calc,limits,objective='OE3: métricas cuantitativas; OG: tiempo de viaje',units='Según ejes'):
        fig.suptitle(title,fontsize=16,fontweight='semibold')
        fig.text(.5,.925,f'Run{n} v8 · iteración 0 · 0–24 h',ha='center',fontsize=10)
        fig.text(.04,.015,limits,fontsize=8.5,va='bottom',wrap=True)
        fig.tight_layout(rect=(.01,.10,.99,.89))
        pub.save(fig,stem,data,dict(title=title,objective=objective,units=units,calculation=calc,
            interpretation=title+'. Estadística descriptiva del escenario simulado.',limitations=limits,
            filters='Identidad nativa exacta; lifecycle completo verificado; sin imputación',
            denominators='Solicitudes por familia; buses por expedición salvo activos/flota',
            exclusions='Duraciones: sólo completos; esperas: sólo incorporados; censurados declarados por separado'))
        notes.append((stem,title,calc,limits,objective))
    x=np.arange(5)
    fig,axes=plt.subplots(2,2,figsize=(13,8))
    for j,(k,lab) in enumerate((('mean_minutes','Media'),('median_minutes','Mediana'),('p90_minutes','P90'),('p95_minutes','P95'))):
        axes[0,0].bar(x+(j-1.5)*.19,[r[k] for r in totals],width=.18,label=lab)
    axes[0,0].set_ylabel('Duración de completos (min)'); axes[0,0].legend(ncols=2)
    bottom=np.zeros(5)
    for k,lab,c in [('completed','Completos','#009e73'),('censored','Censurados','#e69f00'),('not_started','No iniciados','#94a3b8'),('aborted_before_cut','Abortados antes del corte','#d55e00')]:
        vals=np.array([r[k] for r in totals]);axes[0,1].bar(x,vals,bottom=bottom,label=lab,color=c);bottom+=vals
    axes[0,1].set_ylabel('Solicitudes / expediciones');axes[0,1].legend(fontsize=8)
    for ax,k,lab in [(axes[1,0],'peak_active','Máximo simultáneo (vehículos)'),(axes[1,1],'wait_mean_minutes','Espera media de incorporación (min)')]:
        ax.bar(x,[r[k] for r in totals],color=[COLOR[g] for g in GROUPS]);ax.set_ylabel(lab)
    for ax in axes.flat:ax.set_xticks(x,[LABEL[g] for g in GROUPS],rotation=15);ax.grid(axis='y',alpha=.2)
    save(fig,'resumen_global_familias','Resultados globales por familia',totals,'Duración = llegada − solicitud nativa; percentiles lineales (n−1)p. Pico por barrido exacto de intervalos entrada–salida.',
         'Completos excluyen censura. Buses: expediciones; activos: vehículos físicos. La espera excluye solicitudes aún sin incorporación.')

    fig,axes=plt.subplots(1,2,figsize=(13,6))
    distrows=[];arrays=[]
    for g in GROUPS:
        values=sorted(r['complete_duration_seconds']/60 for r in rows if r['group']==g and r['status']=='completed');arrays.append(values)
        axes[0].step(values,np.arange(1,len(values)+1)/len(values),where='post',color=COLOR[g],label=f'{LABEL[g]} (n={len(values)})')
        distrows += [dict(group=g,rank=i+1,minutes=v,cumulative_fraction=(i+1)/len(values)) for i,v in enumerate(values)]
    bp=axes[1].boxplot(arrays,tick_labels=[LABEL[g] for g in GROUPS],showfliers=False,patch_artist=True)
    for p,g in zip(bp['boxes'],GROUPS):p.set_facecolor(COLOR[g]);p.set_alpha(.65)
    axes[0].set(xlabel='Duración de completos (min)',ylabel='Fracción acumulada');axes[0].legend(fontsize=8)
    axes[1].set(ylabel='Duración (min)');axes[1].tick_params(axis='x',rotation=20)
    save(fig,'distribucion_tiempos_familias','Distribución de tiempos por familia',distrows,'ECDF exacta; caja Q1–Q3, mediana y bigotes 1.5×IQR. Outliers omitidos sólo en caja, presentes en ECDF y CSV.',
         'Sólo viajes completados; servicios de bus y OD privados tienen recorridos distintos. No interpreta las diferencias como efecto causal del tipo.')

    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True)
    for g in GROUPS:
        a=[r for r in hourly if r['group']==g]
        for ax,key in zip(axes,('departure','arrival','mean_active')):
            ax.step(range(25),[r[key] for r in a]+[a[-1][key]],where='post',label=LABEL[g],color=COLOR[g])
    for ax,lab in zip(axes,('Solicitudes nativas / h','Llegadas / h','Activos medios (vehículos)')):ax.set_ylabel(lab);ax.grid(alpha=.2);ax.legend(ncols=5,fontsize=8)
    axes[-1].set(xlabel='Hora simulada',xticks=range(0,25,2),xlim=(0,24))
    save(fig,'cronologia_familias','Salidas, llegadas y vehículos activos por hora',hourly,'Cada evento en su hora [h,h+1); activos medios = integral exacta de intervalos físicos / 3600.',
         'Las salidas son solicitudes, no incorporaciones. Las llegadas se ubican por hora real de llegada; el promedio horario no es el pico.')

    demand=[]; fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True)
    for ax,groups in zip(axes,(GROUPS[:3],GROUPS[3:])):
        bottom=np.zeros(24)
        for g in groups:
            values=np.array([r['scheduled_departure'] for r in hourly if r['group']==g])
            ax.bar(np.arange(24)+.5,values,bottom=bottom,width=.9,color=COLOR[g],label=LABEL[g]);bottom+=values
            demand.extend(dict(group=g,hour=h,scheduled=int(v)) for h,v in enumerate(values))
        ax.set_ylabel('Programadas / hora');ax.legend(ncols=3);ax.grid(axis='y',alpha=.2)
    axes[-1].set(xlabel='Hora programada',xticks=range(0,25,2),xlim=(0,24))
    save(fig,'demanda_programada_familias','Demanda programada por familia y hora',demand,'Conteo del censo completo según scheduled_departure en [h,h+1). Oferta pública en panel separado.',
         'N cuenta privados y camiones; la oferta de buses es independiente. Ceros se respaldan en cobertura completa; perfiles de demanda sintéticos.')

    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True)
    for g in GROUPS:
        a=[r for r in hourly if r['group']==g]
        for ax,key in zip(axes,('mean_minutes','median_minutes','wait_mean_minutes')):
            ax.plot(np.arange(24)+.5,[r[key] if r[key] is not None else np.nan for r in a],marker='.',color=COLOR[g],label=LABEL[g])
    for ax,lab in zip(axes,('Media de completos (min)','Mediana de completos (min)','Espera de entrada media (min)')):ax.set_ylabel(lab);ax.grid(alpha=.2);ax.legend(ncols=5,fontsize=8)
    axes[-1].set(xlabel='Hora de solicitud nativa',xticks=range(0,25,2),xlim=(0,24))
    save(fig,'tiempos_y_espera_por_hora','Duración y espera por hora de solicitud',hourly,'Agrupación por departure; duración sólo completos; espera = traffic_entry − departure para incorporados.',
         'Huecos = sin muestra, no cero. La espera de incorporación no mide cola dentro de la red; censuras quedan fuera de percentiles.')

    service=[]
    for svc in bundle['manifest']['public_transport']['service_counts']:
        a=[r for r in rows if r['service']==svc['service_id']]
        service.append(dict(service=svc['service_id'],fleet=len(svc['configured_vehicle_ids']),scheduled=len(a),started=sum(r['departure'] is not None for r in a),
            completed=sum(r['status']=='completed' for r in a),**distribution([r['complete_duration_seconds']/60 for r in a if r['status']=='completed']),**active_metrics(a)))
    fig,axes=plt.subplots(1,3,figsize=(15,7));y=np.arange(len(service));names=[r['service'].replace('transmetro_','TM ').replace('tubus_','TuBus ') for r in service]
    axes[0].barh(y,[r['scheduled'] for r in service],color='#cbd5e1',label='Programadas');axes[0].barh(y,[r['completed'] for r in service],color='#009e73',label='Completadas');axes[0].legend()
    axes[0].set_xlabel('Expediciones')
    axes[1].barh(y,[r['mean_minutes'] for r in service],color='#8064a2');axes[1].set_xlabel('Duración media (min)')
    axes[2].barh(y-.18,[r['fleet'] for r in service],height=.35,color='#cbd5e1',label='Flota');axes[2].barh(y+.18,[r['peak_active'] for r in service],height=.35,color='#cc79a7',label='Pico activo');axes[2].set_xlabel('Vehículos físicos');axes[2].legend()
    for ax in axes:ax.set_yticks(y,names);ax.invert_yaxis();ax.grid(axis='x',alpha=.2)
    save(fig,'transporte_publico_servicios','Oferta y ejecución por línea de transporte público',service,'Servicios e IDs de flota del manifiesto; expediciones del censo completo; duración departure–arrival; pico físico por intervalos nativos.',
         'No mide pasajeros ni asientos. No iniciada ≠ abortada. Duración sólo de completos; excluye retraso entre programación e inicio nativo.')

    freight=bundle['freight_rows'];fr=[]
    for route in sorted({r['route_id'] for r in freight}):
        a=[r for r in freight if r['route_id']==route]
        vals=[(r['arrival_seconds']-r['entry_seconds'])/60 for r in a if r['trip_outcome']=='completed']
        fr.append(dict(route_id=route,scheduled=len(a),completed=sum(r['trip_outcome']=='completed' for r in a),nominal=sum(r['classification']=='nominal' for r in a),**distribution(vals),
            windows_seconds=sorted({str(r['assigned_window_seconds']) for r in a}),policy=sorted({r['policy'] for r in a})))
    fig,axes=plt.subplots(1,2,figsize=(13,6));y=np.arange(len(fr));names=[r['route_id'].replace('-', ' ') for r in fr]
    axes[0].barh(y,[r['scheduled'] for r in fr],color='#cbd5e1',label='Programados');axes[0].barh(y,[r['completed'] for r in fr],color='#b0792a',label='Completos');axes[0].set_xlabel('Camiones');axes[0].legend()
    axes[1].barh(y-.18,[r['median_minutes'] for r in fr],height=.35,color='#b0792a',label='Mediana');axes[1].barh(y+.18,[r['p95_minutes'] for r in fr],height=.35,color='#d55e00',label='P95');axes[1].set_xlabel('Tiempo en red de completos (min)');axes[1].legend()
    for ax in axes:ax.set_yticks(y,names);ax.invert_yaxis();ax.grid(axis='x',alpha=.2)
    save(fig,'carga_rutas_ventanas','Camiones: recorridos y duración en red',fr,'Freight-completion verificado; tiempo llegada − incorporación; rutas fijas, clasificación y ventanas originales en CSV/JSON.',
         'Ventanas y deadline son política configurada, no retiros forzados. Se observa sólo 0–24 h; algunas ventanas declaradas terminan después del corte.')

    odrows=[]
    for r in rows:
        if r['family'] not in ('carro','moto'):continue
        od=json.loads(r['od']) if r['od'] else {}
        if len(od)!=1:raise ValueError('Private OD must be explicit')
        r['od_class']=next(iter(od.values()))['od_class']
    for od in sorted({r['od_class'] for r in rows if 'od_class' in r}):
        a=[r for r in rows if r.get('od_class')==od]
        odrows.append(dict(od_class=od,scheduled=len(a),completed=sum(r['status']=='completed' for r in a),censored=sum(r['status']!='completed' for r in a),**distribution([r['complete_duration_seconds']/60 for r in a if r['status']=='completed'])))
    fig,axes=plt.subplots(2,1,figsize=(12,8));x=np.arange(len(odrows))
    axes[0].bar(x,[r['completed'] for r in odrows],color='#009e73',label='Completos');axes[0].bar(x,[r['censored'] for r in odrows],bottom=[r['completed'] for r in odrows],color='#e69f00',label='Censurados');axes[0].set_ylabel('Viajes privados');axes[0].legend()
    for k,offset,color,lab in [('median_minutes',-.18,'#0072b2','Mediana'),('p95_minutes',.18,'#d55e00','P95')]:axes[1].bar(x+offset,[r[k] for r in odrows],width=.35,color=color,label=lab)
    axes[1].set_ylabel('Duración de completos (min)');axes[1].legend()
    odn={'EXTERNAL_EXTERNAL_THROUGH':'Externo → externo','EXTERNAL_INTERNAL':'Externo → interno','INTERNAL_EXTERNAL':'Interno → externo','INTERNAL_INTERNAL':'Interno → interno'}
    for ax in axes:ax.set_xticks(x,[odn[r['od_class']] for r in odrows]);ax.grid(axis='y',alpha=.2)
    save(fig,'tiempos_clases_od','Tiempos y completitud por clase de origen–destino',odrows,'Clase OD declarada en censo; duración arrival−departure de completos, percentiles lineales.',
         'Clases OD agregan pares distintos. No son un corredor A–B único ni tiempos puerta a puerta fuera de la red simulada.')
    manifest=pub.finish()
    lines=['# Figuras complementarias por corrida','',f'Run ID `{bundle["identity"]["run_id"]}`, iteración 0. N no público = {n}.','',
           'Todas las tablas se verifican contra el censo publicado. Colores de familias constantes entre escenarios.','']
    for stem,title,calc,limit,obj in notes:
        lines += [f'## {title}', '',f'[PNG]({stem}.png) · [SVG]({stem}.svg) · [CSV]({stem}.csv) · [JSON]({stem}.json)','',f'Objetivo: {obj}. Cálculo: {calc}', '',f'Interpretación y límite: {limit}','']
    (pub.directory/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    write_json(pub.directory/'metricas-resumen.json',dict(identity=bundle['identity'],families=totals,service=service,freight=fr))
    return manifest


def generate(output, force=False):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT/'scenarios'): raise ValueError('Output must be outside native scenarios')
    output.mkdir(parents=True,exist_ok=True);style();results=[]
    for folder, native in RUNS:
        bundle=load_bundle(ROOT/'scenarios/zona1/montecarlo'/native,0)
        dest=output/folder; dest.mkdir(parents=True,exist_ok=True)
        original=dest/'official'/bundle['identity']['run_id']/'it.0'
        if not original.exists():
            generate_individual(bundle,dest)
        elif force and bundle['identity']['N_configured'] != 1000:
            with tempfile.TemporaryDirectory(prefix='thesis-core-') as td:
                generated=generate_individual(bundle,Path(td));shutil.copytree(generated,original,dirs_exist_ok=True)
        extended=dest/'complementos';receipt=extended/'figures-manifest.json'
        current=json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() else None
        valid=current and current['source_versions'].get('collection_recipe_sha256')==sha(__file__) and current['identities']==[bundle['identity']]
        if valid:
            valid=all(sha(extended/f['path'])==f['sha256'] for rec in current['figures'] for f in rec['files'])
        if not valid or force:
            with tempfile.TemporaryDirectory(prefix='thesis-runs-') as td:
                stage=Path(td)/'complementos';render(bundle,stage);shutil.copytree(stage,extended,dirs_exist_ok=True)
        results.append(dict(directory=str(dest),identity=bundle['identity']))
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'graficas_tesis_v2');p.add_argument('--force',action='store_true');a=p.parse_args()
    print(json.dumps(generate(a.output,a.force),ensure_ascii=False))
