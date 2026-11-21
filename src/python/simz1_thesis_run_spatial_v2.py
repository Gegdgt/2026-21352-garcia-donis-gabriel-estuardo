"""Per-run spatial plots from the shared, verified read-only replay extract."""
import csv
import json
from pathlib import Path
import shutil
import tempfile
from collections import defaultdict
import numpy as np
import matplotlib.pyplot as plt
from simz1_thesis import Publisher, load_bundle, sha, style, read_json
from simz1_thesis_runs_v2 import ROOT, RUNS


def read_table(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return [{k:(v if k=='link_id' else float(v)) for k,v in row.items()} for row in csv.DictReader(f)]


def generate(output=ROOT/'graficas_tesis_v2'):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT/'scenarios'):raise ValueError('Native output forbidden')
    summaries=[];hours=[];sources=[];b=[]
    for label,(_,native) in zip(('run1000','run10000'),RUNS):
        bundle=load_bundle(ROOT/'scenarios/zona1/montecarlo'/native,0);b.append(bundle)
        folder=output/'datos-espaciales'/label;manifest=read_json(folder/'manifest.json')
        if manifest['identity']['run_id']!=bundle['identity']['run_id'] or manifest['identity']['run_manifest_sha256']!=bundle['identity']['manifest_sha256']:raise ValueError('Spatial identity mismatch')
        records=[]
        for r in manifest['outputs']:
            if sha(r['path'])!=r['sha256']:raise ValueError('Spatial data hash mismatch')
            records.append(dict(r,kind='verified_spatial_extract',verification='pinned replay, native lifecycle coverage and file hash'))
        records.append(dict(path=str(folder/'manifest.json'),sha256=sha(folder/'manifest.json'),kind='spatial_extract_provenance'))
        sources.append(records)
        summaries.append({r['link_id']:r for r in read_table(folder/'link_summary.csv')})
        hours.append(read_table(folder/'link_hourly.csv'))
    pooled=defaultdict(lambda:dict(entries=0,vehicle_seconds=0))
    for rows in summaries:
        for k,r in rows.items():
            for metric in ('entries','vehicle_seconds'):pooled[k][metric]+=r[metric]
    with (output/'mapas-red-vial/network-links.csv').open(encoding='utf-8-sig',newline='') as stream:
        network={r['link_id']:r for r in csv.DictReader(stream)}
    network_table=output/'mapas-red-vial/network-links.csv'
    for records in sources:records.append(dict(path=str(network_table),sha256=sha(network_table),kind='native_network_attribute_extract'))
    flow=[];seen=set()
    for link in sorted(pooled,key=lambda k:(-pooled[k]['entries'],k)):
        name=network[link].get('osm_name','').strip()
        if name and name not in seen:flow.append(link);seen.add(name)
        if len(flow)==4:break
    if len(flow)!=4:raise ValueError('Four named representative road sections required')
    critical=sorted(pooled,key=lambda k:(-pooled[k]['vehicle_seconds'],k))[:4]
    style();results=[]
    for index,(name,_) in enumerate(RUNS):
        with tempfile.TemporaryDirectory(prefix='thesis-link-') as td:
            stage=Path(td)/'published';bundle=b[index]
            pub=Publisher(stage,[bundle['identity']],sources[index],dict(spatial_recipe_sha256=sha(__file__)))
            notes=[]
            def save(fig,stem,title,rows,method,limit):
                fig.suptitle(title,fontsize=16,fontweight='semibold')
                fig.text(.5,.925,f'Run{bundle["identity"]["N_configured"]} v8 · iteración 0 · 0–24 h',ha='center')
                fig.text(.04,.012,limit,fontsize=8.5)
                fig.tight_layout(rect=(.01,.11,.99,.89))
                pub.save(fig,stem,rows,dict(title=title,objective='OE3: flujo y acumulación; OE2: escenario de carga',
                    units='Según ejes',calculation=method,interpretation=title,limitations=limit,
                    filters='Red nativa; todas las familias; ventana completa 0–86400 s',
                    denominators='Transiciones LinkEnter y segundos-vehículo asociados; no vehículos únicos',
                    exclusions='No se imputa asociación espacial ausente; ver coverage_hourly.csv'))
                notes.append((stem,title,method,limit))
            top=sorted(summaries[index].values(),key=lambda r:(-r['entries'],r['link_id']))[:12]
            fig,ax=plt.subplots(figsize=(12,7));y=np.arange(len(top))
            ax.barh(y,[r['entries'] for r in top],color=('#0072b2','#d55e00')[index]);ax.set_yticks(y,[r['link_id'] for r in top]);ax.invert_yaxis();ax.set_xlabel('Transiciones de entrada al enlace / 24 h');ax.grid(axis='x',alpha=.2)
            save(fig,'flujo_top_enlaces','Enlaces con mayor flujo observado',top,'Doce enlaces con mayor total LinkEnter nativo; desempate por ID. VehicleEntersTraffic se conserva separado en respaldo.',
                 'Un vehículo puede pasar varias veces. Sumar enlaces sucesivos duplica recorridos; esto no es flujo total de un corredor.')
            fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True);data=[]
            for ax,link in zip(axes.flat,flow):
                a=[r for r in hours[index] if r['link_id']==link]
                if len(a)!=24: raise ValueError('No complete hourly support for selected section')
                data += [dict(r,road_name=network[link]['osm_name']) for r in a];ax.step(range(25),[r['entries'] for r in a]+[a[-1]['entries']],where='post',color=('#0072b2','#d55e00')[index]);ax.set_title(network[link]['osm_name']+'\n'+link,fontsize=9);ax.set(xlim=(0,24),xticks=range(0,25,4),xlabel='Hora simulada',ylabel='Transiciones / hora');ax.grid(alpha=.2)
            save(fig,'flujo_secciones_por_hora','Flujo horario en secciones comunes',data,'Selección exploratoria: ordenar enlaces por suma LinkEnter entre ambas cargas, desempate ID; tomar primero de cada osm_name no vacío hasta cuatro vías distintas.',
                 'Secciones comunes elegidas después de observar resultados; no aforos calibrados ni suma de flujo a lo largo de calles.')
            fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True);data=[]
            for ax,link in zip(axes.flat,critical):
                a=[r for r in hours[index] if r['link_id']==link]
                if len(a)!=24:raise ValueError('No complete support for critical link')
                data+=a;ax.plot(np.arange(24)+.5,[r['mean_active'] for r in a],color=('#0072b2','#d55e00')[index],label='Media horaria');ax.plot(np.arange(24)+.5,[r['peak_active'] for r in a],color='#64748b',ls='--',label='Pico horario');ax.set_title(link,fontsize=9);ax.set(xlim=(0,24),xticks=range(0,25,4),xlabel='Hora simulada',ylabel='Vehículos asociados');ax.grid(alpha=.2);ax.legend(fontsize=8)
            save(fig,'acumulacion_enlaces_criticos','Acumulación en enlaces críticos',data,'Cuatro enlaces por mayor suma de segundos-vehículo entre cargas. Media=integral de asociación/3600; pico simultáneo exacto dentro de cada hora.',
                 'Proxy por enlace: no cola en intersección ni posición corporal. No sumar picos. Cobertura faltante declarada en datos-espaciales.')
            result=pub.finish();dest=output/name/'espacial';dest.mkdir(parents=True,exist_ok=True)
            lines=['# Flujo y acumulación por corrida','','Selección común entre cargas, calculada exclusivamente con el extracto espacial compartido.','']
            for stem,title,method,limit in notes:lines += [f'## {title}','',f'[PNG]({stem}.png) · [SVG]({stem}.svg) · [CSV]({stem}.csv) · [JSON]({stem}.json)','',method,'',limit,'']
            (stage/'README.md').write_text('\n'.join(lines),encoding='utf-8')
            shutil.copytree(stage,dest,dirs_exist_ok=True);results.append(result)
    return results


if __name__=='__main__':
    print(json.dumps(dict(status='generated',groups=len(generate()))))
