"""Read-only thesis maps of the two explicitly selected SimZ1 v8 runs.

Network topology is authoritative; local plots do not certify GIS accuracy.
No events, replay database or simulation launcher are opened by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import BoundaryNorm, Normalize
from matplotlib.lines import Line2D
import numpy as np

from simz1_thesis import read_json, write_json, sha, verified
from simz1_thesis_spatial import _separate_annotations

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'simz1-thesis-maps-v2.2'
RUNS = [('run1000', 'run-bg1-a32f15487b1a49ac910ba799175658ca'),
        ('run10000', 'run-bg10-e496c091b9ef46ee9ca381576135e299')]
COLORS = ['#0072B2', '#D55E00', '#009E73', '#CC79A7']
GEOMETRY_LIMIT = ('Geometría local aproximada, no cartografía GIS verificada. '
                  'Los trazos unen los nodos de cada enlace; no representan anchura ni posición corporal.')


def read_network(path):
    nodes, links, crs = {}, {}, None
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        for _, e in ET.iterparse(stream, events=('end',)):
            tag = e.tag.split('}')[-1]
            if tag == 'attribute' and e.get('name') == 'coordinateReferenceSystem':
                crs = e.text
            elif tag == 'node':
                nodes[e.get('id')] = {'node_id': e.get('id'), 'x_m': float(e.get('x')), 'y_m': float(e.get('y'))}
                e.clear()
            elif tag == 'link':
                attrs = {a.get('name'): a.text for a in e.findall('./attributes/attribute')}
                row = dict(link_id=e.get('id'), from_node=e.get('from'), to_node=e.get('to'),
                           length_m=float(e.get('length')), lanes=float(e.get('permlanes')),
                           freespeed_kmh=float(e.get('freespeed'))*3.6,
                           capacity_veh_hour=float(e.get('capacity')), modes=','.join(sorted(e.get('modes','').split(','))),
                           osm_name=attrs.get('osm:name', ''), highway=attrs.get('osm:highway', ''),
                           speed_source=attrs.get('physical:speedSource', ''),
                           lanes_source=attrs.get('physical:lanesSource', ''), osm_way=e.get('origid', ''),
                           osm_oneway=attrs.get('osm:oneway', ''))
                links[row['link_id']] = row
                e.clear()
    if not nodes or not links or crs != 'EPSG:32615':
        raise ValueError('Expected nonempty native EPSG:32615 network')
    for row in links.values():
        a, b = nodes[row['from_node']], nodes[row['to_node']]
        row.update(from_x_m=a['x_m'], from_y_m=a['y_m'], to_x_m=b['x_m'], to_y_m=b['y_m'])
        if not all(math.isfinite(row[k]) for k in ['length_m', 'lanes', 'freespeed_kmh', 'capacity_veh_hour']):
            raise ValueError('Non-finite network property')
    return nodes, links, crs


def read_lanes(path):
    rows = []
    with Path(path).open('rb') as stream:
        for _, e in ET.iterparse(stream, events=('end',)):
            if e.tag.split('}')[-1] != 'lanesToLinkAssignment':
                continue
            children = [c for c in e if c.tag.split('}')[-1] == 'lane']
            physical = [c for c in children if not c.get('id', '').endswith('.original')]
            rows.append(dict(link_id=e.get('linkIdRef'), lane_objects=len(physical),
                             original_queue_objects=len(children)-len(physical),
                             lane_ids=';'.join(c.get('id') for c in physical)))
            e.clear()
    return rows


def read_signals(path, links):
    root = ET.parse(path).getroot()
    rows = []
    for system in root:
        if system.tag.split('}')[-1] != 'signalSystem':
            continue
        for e in system.iter():
            if e.tag.split('}')[-1] == 'signal':
                lid = e.get('linkIdRef')
                if lid not in links:
                    raise ValueError('Controlled link missing from native network')
                link = links[lid]
                rows.append(dict(system_id=system.get('id'), signal_id=e.get('id'), link_id=lid,
                                 node_id=link['to_node'], x_m=link['to_x_m'], y_m=link['to_y_m']))
    return rows


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        raise ValueError('Refuse an empty backing table')
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def load_runs():
    result = []
    for label, folder in RUNS:
        run = ROOT/'scenarios/zona1/montecarlo'/folder
        m = read_json(run/'run-manifest.json')
        if m.get('status') != 'completed' or m.get('validation', {}).get('status') != 'valid' or 0 not in m['iterations']['completed']:
            raise ValueError('Selected run not completed/valid at iteration zero')
        network = verified(run, m['results']['0']['network'])
        lanes = verified(run, m['inputs']['input:transit-weekday/lanes.xml'])
        systems = verified(run, m['inputs']['input:signalsystems-signalsystems.xml'])
        control = verified(run, m['inputs']['input:signalsystems-signalcontrol.xml'])
        trips = run/'analysis/it.0/trips.csv.gz'
        analysis = read_json(run/'analysis/it.0/analysis-manifest.json')
        trip_record = next(r for r in analysis['artifacts'] if r['path'].endswith('/trips.csv.gz') or r['path'] == 'trips.csv.gz')
        # Analytical artifacts are relative to the iteration's analysis directory.
        trips = verified(run/'analysis/it.0', trip_record)
        result.append(dict(label=label, run=run, manifest=m, network=network, lanes=lanes,
                           signals=systems, signal_control=control, trips=trips,
                           run_id=m['run_id'], launch_id=m.get('launch_id')))
    return result


def select_ab(runs, links, out):
    counts, observations = [], []
    for run in runs:
        counter, rows = Counter(), []
        with gzip.open(run['trips'], 'rt', encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['run_id'] != run['run_id'] or row['iteration'] != '0':
                    raise ValueError('A–B trip identity mismatch')
                if row['status'] != 'completed' or not row['person_id'].startswith('z1_'):
                    continue
                a, b = row['departure_link'], row['arrival_link']
                if not a or not b or a == b:
                    continue
                if a not in links or b not in links:
                    raise ValueError('Observed A–B endpoint missing from simulated network')
                counter[a, b] += 1
                rows.append(row)
        counts.append(counter); observations.append(rows)
    common = set(counts[0]) & set(counts[1])
    ranked = sorted(common, key=lambda p: (-min(counts[0][p], counts[1][p]), p))
    selected = ranked[:4]
    write_csv(out/'ab-pares-comunes.csv', [dict(rank=i+1,origin_link=a,destination_link=b,
        n_run1000=counts[0][a,b],n_run10000=counts[1][a,b],selection_score=min(counts[0][a,b],counts[1][a,b]))
        for i,(a,b) in enumerate(ranked)])
    pairs = [dict(candidate=i+1, origin_link=a, destination_link=b,
                  n_run1000=counts[0][a,b], n_run10000=counts[1][a,b],
                  selection_score=min(counts[0][a,b], counts[1][a,b])) for i,(a,b) in enumerate(selected)]
    if not pairs:
        raise ValueError('No common observable private A–B candidates')
    selected_lookup = {(r['origin_link'],r['destination_link']):r['candidate'] for r in pairs}
    exact = []
    for run, rows in zip(runs, observations):
        for r in rows:
            pair = r['departure_link'],r['arrival_link']
            if pair in selected_lookup:
                exact.append(dict(candidate=selected_lookup[pair], scenario=run['label'],
                    run_id=run['run_id'], iteration=0, person_id=r['person_id'], vehicle_id=r['vehicle_id'],
                    origin_link=pair[0], destination_link=pair[1], profile=r['profile'],
                    departure_seconds=float(r['departure']), arrival_seconds=float(r['arrival']),
                    duration_seconds=float(r['duration_seconds'])))
    write_csv(out/'ab-candidatos.csv', pairs)
    write_csv(out/'ab-observaciones.csv', exact)
    write_json(out/'ab-metodologia.json', dict(version=VERSION, candidates=pairs,
        selection='Top cuatro pares dirigidos de enlaces presentes en ambas corridas por min(n_1k,n_10k) descendente; empate lexicográfico.',
        eligible='Viajes privados z1_ con estado completed, extremos distintos y en la red; iteración 0.',
        common_pairs=len(common), observations=len(exact),
        duration='arrival minus departure, seconds; includes incorporation wait; not a fixed trajectory traversal time.',
        limitation='Selección exploratoria posterior a observar resultados; no A–B preespecificado, no ruta fija ni control de mezcla de perfiles; excluye censuras.'))
    return pairs


class MapPublisher:
    def __init__(self, out, runs, nodes, links, crs):
        self.out, self.runs, self.nodes, self.links, self.crs = out, runs, nodes, links, crs
        self.x0 = min(r['x_m'] for r in nodes.values())
        self.y0 = min(r['y_m'] for r in nodes.values())
        self.figures = []
        self.extra_sources=[]
        self.spatial_coverage=[]
        self.ids = list(links)
        self.segments = np.array([[[r['from_x_m'],r['from_y_m']],[r['to_x_m'],r['to_y_m']]] for r in links.values()])
        self.segments = (self.segments-np.array([self.x0,self.y0]))/1000
        plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':12,
                             'svg.fonttype':'none','savefig.dpi':300,'axes.spines.top':False,'axes.spines.right':False})

    def frame(self, title, subtitle=None, two=False):
        fig, axes = plt.subplots(1,2 if two else 1,figsize=(13.5,8) if two else (9.8,9.6))
        for ax in np.atleast_1d(axes):
            ax.add_collection(LineCollection(self.segments, colors='#cbd5e1', linewidths=.5,alpha=.6))
            ax.autoscale();ax.set_aspect('equal');ax.grid(alpha=.12)
            ax.set_xlabel('Este local (km)');ax.set_ylabel('Norte local (km)')
        fig.suptitle(title,fontsize=17,weight='bold',y=.975)
        fig.text(.5,.94,subtitle or 'Red simulada común · Run1000 y Run10K v8 · iteración 0',ha='center',fontsize=10,color='#475569')
        fig.text(.075,.028,'UTM 15N (EPSG:32615), origen local: '+f'{self.x0:.1f} E, {self.y0:.1f} N m.\nGeometría aproximada; no GIS verificada. Fuente OSM: © OpenStreetMap contributors (ODbL).',fontsize=8.5,color='#475569')
        fig.subplots_adjust(left=.08,right=.92,top=.90,bottom=.105,wspace=.26)
        return fig, axes

    def save(self, fig, name, rows, title, calculation, interpretation, limitation=GEOMETRY_LIMIT, objective='OE1', sources=None):
        fig.savefig(self.out/(name+'.png'),dpi=300,facecolor='white')
        fig.savefig(self.out/(name+'.svg'),facecolor='white')
        plt.close(fig)
        write_csv(self.out/(name+'.csv'),rows)
        record = dict(name=name,title=title,objective=objective,variable=title,calculation=calculation,
                      interpretation=interpretation,limitation=limitation,
                      sources=sources or ['native output_network.xml.gz'],
                      identity=[dict(scenario=r['label'],run_id=r['run_id'],launch_id=r['launch_id'],iteration=0) for r in self.runs],
                      files={ext:name+'.'+ext for ext in ('png','svg','csv','json')})
        write_json(self.out/(name+'.json'),record)
        self.figures.append(record)

    def color(self, ax, values, label, cmap='viridis', norm=None, linewidth=1.2):
        collection=LineCollection(self.segments,cmap=cmap,norm=norm,linewidths=linewidth)
        collection.set_array(np.asarray(values,dtype=float));ax.add_collection(collection)
        plt.colorbar(collection,ax=ax,fraction=.035,pad=.025,label=label,shrink=.85)
        return collection


def structures(pub, runs, pairs):
    rows=list(pub.links.values());nodes=list(pub.nodes.values())
    fig,ax=pub.frame('Red vial utilizada por MATSim')
    styles={'primary':('#123c55',1.45),'secondary':('#247695',1.15),'tertiary':('#5b99a6',.9),'residential':('#8896a1',.55)}
    highway_counts=Counter(r['highway'] or 'sin etiqueta' for r in rows)
    for highway,(color,lw) in styles.items():
        ix=[i for i,r in enumerate(rows) if r['highway']==highway]
        ax.add_collection(LineCollection(pub.segments[ix],colors=color,linewidths=lw))
    handles=[Line2D([0],[0],color=c,lw=2,label=f'{k}: {highway_counts[k]} enlaces') for k,(c,_) in styles.items()]
    handles.append(Line2D([0],[0],color='#cbd5e1',lw=2,label='Otras categorías / conectores'))
    ax.legend(handles=handles,loc='lower left',fontsize=9,framealpha=.96)
    pub.save(fig,'mapa_01_red_base',rows,'Red vial por jerarquía OSM','Geometría from→to de cada enlace nativo; clasificación osm:highway.',
             f'{len(nodes)} nodos y {len(rows)} enlaces dirigidos modelados; la jerarquía ayuda a localizar avenidas y calles principales.')

    fig,ax=pub.frame('Nodos y conectividad de la red simulada')
    degree=Counter()
    for r in rows: degree[r['from_node']]+=1;degree[r['to_node']]+=1
    xy=np.array([[(r['x_m']-pub.x0)/1000,(r['y_m']-pub.y0)/1000] for r in nodes])
    ax.scatter(xy[:,0],xy[:,1],s=4,c='#0072B2',alpha=.65,label=f'{len(nodes)} nodos')
    high=[i for i,r in enumerate(nodes) if degree[r['node_id']]>=6]
    ax.scatter(xy[high,0],xy[high,1],s=16,c='#D55E00',label='Grado dirigido ≥ 6')
    ax.legend(loc='lower left',fontsize=9)
    pub.save(fig,'mapa_02_nodos', [{**r,'directed_degree':degree[r['node_id']]} for r in nodes],
             'Nodos de red y grado dirigido','Grado = enlaces entrantes + salientes, incluidos enlaces paralelos.',
             'Localiza conectividad modelada; un nodo no necesariamente es una intersección física independiente.')

    fig,axes=pub.frame('Enlaces dirigidos: conectividad y detalle',two=True)
    midpoint=pub.segments.mean(axis=1);delta=pub.segments[:,1,:]-pub.segments[:,0,:]
    for ax in axes:
        ax.quiver(midpoint[:,0],midpoint[:,1],delta[:,0]*.6,delta[:,1]*.6,
                  angles='xy',scale_units='xy',scale=1,width=.0018,color='#0072B2',headwidth=3.5,headlength=4)
    axes[0].set_title('Dominio completo')
    cx,cy=np.median(midpoint,axis=0);axes[1].set_xlim(cx-.30,cx+.30);axes[1].set_ylim(cy-.30,cy+.30)
    axes[1].set_title('Detalle central (600 × 600 m)')
    pub.save(fig,'mapa_03_enlaces_dirigidos',rows,'Enlaces dirigidos','Flecha según from_node→to_node; longitud gráfica 60% del enlace.',
             'Las flechas describen dirección permitida en el grafo; no son velocidades observadas.')

    fig,ax=pub.frame('Carriles modelados por enlace')
    pub.color(ax,[r['lanes'] for r in rows],'Carriles declarados (permlanes)',norm=Normalize(1,max(r['lanes'] for r in rows)))
    lane_table=read_lanes(runs[0]['lanes']);lookup={r['link_id']:r for r in lane_table}
    pub.save(fig,'mapa_04_carriles',[{**r,**lookup.get(r['link_id'],{})} for r in rows],
        'Número de carriles modelados','Color = permlanes del network; tabla añade lane objects de lanes.xml, excluyendo .original del conteo de carriles.',
        'Muestra oferta de carriles y objetos de asignación; los objetos .original son colas originales, no carriles físicos adicionales.',
        GEOMETRY_LIMIT+' No se inventa una separación lateral de carriles; los valores pueden provenir de supuestos del importador.',
        sources=['native output_network.xml.gz','inputs/transit-weekday/lanes.xml'])

    directed={(r['from_node'],r['to_node']) for r in rows}
    reciprocal=[int((r['to_node'],r['from_node']) in directed) for r in rows]
    fig,ax=pub.frame('Sentidos de circulación en el grafo')
    for val,color,label in [(0,'#0072B2','Sin enlace recíproco exacto'),(1,'#D55E00','Con enlace recíproco exacto')]:
        ix=[i for i,v in enumerate(reciprocal) if v==val]
        ax.add_collection(LineCollection(pub.segments[ix],colors=color,linewidths=.9,label=f'{label} ({len(ix)})'))
    ax.legend(loc='lower left',fontsize=9)
    pub.save(fig,'mapa_05_sentidos',[{**r,'has_reverse_node_pair':v} for r,v in zip(rows,reciprocal)],
        'Sentidos de circulación','Para enlace (u,v), buscar (v,u) en el grafo; no usar oneway=1 de MATSim como prueba de calle unidireccional.',
        'Distingue conectividad recíproca exacta; las calzadas separadas con nodos distintos requieren otra interpretación.',
        GEOMETRY_LIMIT+' Ausencia de enlace recíproco no certifica por sí sola una calle de sentido único.')

    signals=read_signals(runs[0]['signals'],pub.links)
    grouped=defaultdict(list)
    for r in signals: grouped[r['system_id']].append(r)
    fig,ax=pub.frame('Sistemas semafóricos y accesos controlados')
    controlled={r['link_id'] for r in signals};ix=[i for i,lid in enumerate(pub.ids) if lid in controlled]
    ax.add_collection(LineCollection(pub.segments[ix],colors='#D55E00',linewidths=1.25,alpha=.75))
    points=np.array([[np.mean([r['x_m'] for r in rr]),np.mean([r['y_m'] for r in rr])] for rr in grouped.values()])
    points=(points-np.array([pub.x0,pub.y0]))/1000
    ax.scatter(points[:,0],points[:,1],s=22,c='#009E73',edgecolors='white',linewidths=.5,zorder=4,
               label=f'{len(grouped)} sistemas; {len(controlled)} enlaces controlados')
    ax.legend(loc='lower left',fontsize=9)
    pub.save(fig,'mapa_06_semaforos',signals,'Sistemas semafóricos','Accesos signal.linkIdRef; símbolo en media de nodos destino del sistema.',
        'Identifica control semafórico cargado en ambas corridas, sin inferir efectividad ni fase instantánea.',
        GEOMETRY_LIMIT+' Un sistema es una entidad de control; su centro gráfico no es una posición levantada en campo.',
        sources=['native output_network.xml.gz','inputs/signalsystems-signalsystems.xml'])

    fig,ax=pub.frame('Velocidad de flujo libre configurada')
    pub.color(ax,[r['freespeed_kmh'] for r in rows],'Velocidad configurada (km/h)',cmap='cividis')
    pub.save(fig,'mapa_07_velocidad_configurada',rows,'Velocidad de flujo libre','freespeed (m/s) × 3.6; procedencia física preservada en CSV.',
        'Describe el parámetro que utiliza la simulación, distinto de velocidad observada y límite legal verificado.',
        GEOMETRY_LIMIT+' Hay valores asumidos por categoría OSM; no son mediciones ni señalización legal confirmada.')

    fig,ax=pub.frame('Pares A–B observables comunes a 1K y 10K')
    markers=defaultdict(list)
    for r,color in zip(pairs,COLORS):
        for field,marker,prefix in [('origin_link','o','A'),('destination_link','^','B')]:
            markers[r[field]].append((marker,prefix+str(r['candidate']),color))
    for link_id,items in markers.items():
        index=pub.ids.index(link_id);p=pub.segments[index].mean(axis=0)
        color=items[0][2] if len(items)==1 else '#334155'
        label=', '.join(item[1] for item in items)
        ax.add_collection(LineCollection([pub.segments[index]],colors=color,linewidths=3))
        ax.scatter(*p,s=55,color=color,marker=items[0][0],edgecolors='white',zorder=5)
        ax.annotate(label,p,xytext=(7,6 if label.startswith('A') else -12),textcoords='offset points',
                    fontsize=10,color=color,weight='bold',bbox=dict(fc='white',ec='none',alpha=.8,pad=1))
    handles=[Line2D([0],[0],color=c,marker='o',label=f"Par {r['candidate']}: n₁ₖ={r['n_run1000']}, n₁₀ₖ={r['n_run10000']}") for r,c in zip(pairs,COLORS)]
    ax.legend(handles=handles,loc='lower left',fontsize=9)
    pub.save(fig,'mapa_08_candidatos_ab',pairs,'Pares A–B comunes',
        'Top 4 pares privados completados comunes por min(n_1k,n_10k), desempate lexicográfico; A/B en punto medio de enlaces.',
        'Enlaces de salida/llegada observados; no se traza una trayectoria. Tabla ab-observaciones.csv contiene tiempos comprobables.',
        GEOMETRY_LIMIT+' Selección exploratoria posterior; no es una pareja A–B preespecificada ni un recorrido fijo.',
        objective='OG, OE1, OE3',sources=['native output_network.xml.gz','analysis/it.0/trips.csv.gz'])


def osm_comparison(runs):
    paths=[ROOT/'map.osm',ROOT/'scenarios/zona1/map.osm',runs[0]['run']/'inputs/od-source.osm']
    rows=[]
    for path in paths:
        if not path.is_file():
            rows.append(dict(path=str(path.relative_to(ROOT)),exists=False));continue
        data=path.read_bytes(); counts=Counter()
        for _,e in ET.iterparse(path,events=('end',)):
            if e.tag in ('node','way','relation'): counts[e.tag]+=1;e.clear()
        rows.append(dict(path=str(path.relative_to(ROOT)),exists=True,sha256=hashlib.sha256(data).hexdigest(),
                         sha256_lf=hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest(),**counts))
    return rows


def spatial_maps(pub, spatial_dir):
    """Consume only published aggregate CSVs; never reopen a replay database."""
    tables=[]
    for run in pub.runs:
        path=spatial_dir/run['label']/'link_summary.csv'
        manifest_path=path.parent/'manifest.json'
        manifest=read_json(manifest_path)
        identity=manifest.get('identity',{})
        if (identity.get('run_id')!=run['run_id'] or identity.get('iteration')!=0 or
                identity.get('run_manifest_sha256')!=sha(run['run']/'run-manifest.json')):
            raise ValueError('Spatial manifest belongs to a different native run')
        output_record=next((r for r in manifest['outputs'] if Path(r['path']).resolve()==path.resolve()),None)
        if output_record is None or sha(path)!=output_record['sha256']:
            raise ValueError('Spatial table hash differs from its published manifest')
        pub.extra_sources.extend([dict(path=str(p.relative_to(ROOT)),sha256=sha(p),bytes=p.stat().st_size,
            kind='spatial_aggregate',scenario=run['label']) for p in (path,manifest_path)])
        pub.spatial_coverage.append(dict(scenario=run['label'],**manifest['totals']))
        if not path.is_file():
            raise ValueError('Missing spatial table: '+str(path))
        with path.open(encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        lookup={r['link_id']:r for r in rows}
        if len(lookup)!=len(rows) or not set(lookup).issubset(pub.links):
            raise ValueError('Duplicate/foreign link in spatial table')
        for r in rows:
            for key in ('entries','traffic_entries','vehicle_seconds','mean_active','peak_active','coverage_seconds'):
                r[key]=float(r[key])
                if not math.isfinite(r[key]) or r[key]<0:
                    raise ValueError('Invalid aggregate value: '+key)
            if r['coverage_seconds']!=86400:
                raise ValueError('Map requires complete 24-hour link coverage')
        tables.append((run,path,rows,lookup))
    vmax=max(r['entries'] for _,_,rr,_ in tables for r in rr)
    for run,path,rows,lookup in tables:
        label='Run1000' if run['label']=='run1000' else 'Run10K'
        fig,ax=pub.frame('Flujo registrado por enlace · '+label,
            label+' v8 · iteración 0 · día simulado completo, 00:00–24:00')
        values=[lookup[lid]['entries'] if lid in lookup else np.nan for lid in pub.ids]
        pub.color(ax,values,'Entradas LinkEnter (pasos/día)',cmap='magma_r',norm=Normalize(0,vmax),linewidth=1.4)
        pub.save(fig,'mapa_09_flujo_'+run['label'],
            [{**pub.links[r['link_id']],**r} for r in rows], 'Flujo por enlace · '+label,
            'Conteo de eventos entered link por enlace durante [0,86400); se excluye vehicle enters traffic del aforo.',
            'Cada paso por un enlace cuenta una vez; una trayectoria aporta a varios enlaces. Escala de color idéntica entre 1K y 10K.',
            GEOMETRY_LIMIT+' Es flujo por enlace, no vehículos únicos de un corredor. Enlaces ausentes de la tabla se dejan sin valor.',
            objective='OE2, OE3',sources=[str(path.relative_to(ROOT)), 'native output_network.xml.gz'])

    critical=sorted(set().union(*(set(t[3]) for t in tables)),
                    key=lambda lid:(-max(t[3].get(lid,{}).get('vehicle_seconds',0) for t in tables),lid))[:8]
    selected=[dict(rank=i+1,link_id=lid,osm_name=pub.links[lid]['osm_name'],
        vehicle_seconds_run1000=tables[0][3].get(lid,{}).get('vehicle_seconds'),
        vehicle_seconds_run10000=tables[1][3].get(lid,{}).get('vehicle_seconds')) for i,lid in enumerate(critical)]
    write_csv(pub.out/'enlaces-criticos.csv',selected)
    fig,ax=pub.frame('Enlaces críticos por tiempo acumulado de presencia',
                       'Criterio exploratorio común · máximo de vehículo-segundos entre 1K y 10K')
    color='#9e2a2b'
    label_positions=[]
    for r in selected:
        index=pub.ids.index(r['link_id']);p=pub.segments[index].mean(axis=0)
        ax.add_collection(LineCollection([pub.segments[index]],colors=color,linewidths=2.8))
        ax.scatter(*p,s=32,color=color,edgecolors='white',zorder=5)
        label_positions.append((r,p))
    # Keyed labels in a side panel avoid stacking several short consecutive links.
    fig.subplots_adjust(right=.70)
    annotations=[]
    for i,(r,p) in enumerate(label_positions):
        y=.85-i*.085
        annotations.append(ax.annotate(str(r['rank']),p,xytext=(5,4+(i%2)*8),textcoords='offset points',fontsize=9,weight='bold',
                    color=color,bbox=dict(fc='white',ec='none',alpha=.85,pad=.7)))
        fig.text(.735,y,f"{r['rank']}. {r['osm_name'] or 'Sin nombre OSM'}",fontsize=9.5,weight='bold',color=color)
        fig.text(.735,y-.024,r['link_id'].replace('osm_',''),fontsize=7.6)
        def amount(value):
            return f'{value/3600:.1f} veh·h' if value is not None else 'sin registro'
        fig.text(.735,y-.038,f"1K: {amount(r['vehicle_seconds_run1000'])}\n10K: {amount(r['vehicle_seconds_run10000'])}",
                 fontsize=8,va='top',linespacing=1.4)
    _separate_annotations(fig,ax,annotations)
    pub.save(fig,'mapa_10_enlaces_criticos',selected,'Enlaces críticos por presencia',
        'Top 8 enlaces por max(vehículo-segundos_1k, vehículo-segundos_10k), empate por ID. Integración de asociación nativa a enlace.',
        'Acumulación temporal de presencia; puede reflejar volumen, longitud, servicio/paradas y duración de permanencia.',
        GEOMETRY_LIMIT+' Proxy de acumulación en enlaces, no ocupación corporal ni cola semafórica. No prueba saturación ni causalidad.',
        objective='OE2, OE3',sources=[str(t[1].relative_to(ROOT)) for t in tables])
    return [str(t[1]) for t in tables]


def finalize(pub, runs, osm):
    source_records=[]
    for run in runs:
        for kind in ('network','lanes','signals','signal_control','trips'):
            p=run[kind];source_records.append(dict(scenario=run['label'],kind=kind,path=str(p.relative_to(ROOT)),sha256=sha(p),bytes=p.stat().st_size))
    source_records.extend(pub.extra_sources)
    source_records.append(dict(kind='postprocessor',path='python/simz1_thesis_maps_v2.py',sha256=sha(__file__)))
    manifest=dict(schema_version=1,version=VERSION,iteration=0,figures=pub.figures,sources=source_records,
                  spatial_reference=pub.crs,local_origin_m=[pub.x0,pub.y0],osm_comparison=osm,
                  counts=dict(nodes=len(pub.nodes),directed_links=len(pub.links)),
                  network_comparison='Exact parsed node/link properties after normalizing the unordered modes set; output serialization differs in bus,car vs car,bus order.',
                  spatial_coverage=pub.spatial_coverage,
                  simulation_rerun=False,geometry_limit=GEOMETRY_LIMIT)
    write_json(pub.out/'manifest.json',manifest)
    text=['# Mapas de la red vial realmente simulada','',
          'Red de salida nativa, iteración 0, de Run1000 y Run10K v8. Ambas redes se contrastan por estructura completa antes de compartir mapas. '+GEOMETRY_LIMIT,'',
          'El OSM es un extracto fuente; la red MATSim incorpora filtrado, sentidos, parámetros y conectores/servicios. Por ello sus cantidades no deben igualarse. Se preservan hashes y conteos en `manifest.json`. No se descargaron datos nuevos.','',
          'La ruta `map.osm` en la raíz solicitada no existe en el estado revisado. Se encontró `scenarios/zona1/map.osm`, idéntico al snapshot `inputs/od-source.osm` de Run1000. El extracto contiene 14558 nodos, 3174 vías y 93 relaciones; la red procesada usada contiene 4257 nodos y 6240 enlaces dirigidos. Las redes de ambas corridas son semánticamente iguales; su serialización invierte el orden del conjunto de modos `bus,car`/`car,bus` en algunos enlaces. Los hashes originales se conservan.','',
          'Fuente cartográfica: © OpenStreetMap contributors, ODbL. Atribución de la copia local: `scenarios/zona1/osm-source.json`.','',
          '## Figuras','']
    text[2:2]=['Identidades nativas: '+ '; '.join(f"{r['label']}: `{r['run_id']}`, LaunchId `{r['launch_id']}`, iteración 0" for r in runs)+'.','']
    for f in pub.figures:
        text.extend([f"### {f['title']}",'',f"Archivos: [{f['name']}.png]({f['name']}.png), [SVG]({f['name']}.svg), [CSV]({f['name']}.csv), [JSON]({f['name']}.json).",'',
            f"Objetivo: {f['objective']}. Cálculo: {f['calculation']}",'',f"Interpretación: {f['interpretation']}",'',f"Limitación: {f['limitation']}",''])
    text+=['## Selección A–B reproducible','',
           'Pares comunes entre viajes privados completados: ordenar por el mínimo de observaciones entre cargas, descendente, y desempatar por IDs de enlaces. Tomar los primeros cuatro. `ab-candidatos.csv` conserva extremos y n; `ab-observaciones.csv` conserva IDs, perfil y tiempos de eventos. La duración es llegada menos solicitud de salida e incluye espera de incorporación. No demuestra igualdad de rutas ni calibración; es una selección exploratoria después de observar resultados.','',
           '## Regeneración','',
           '`.\\.venv\\Scripts\\python.exe .\\python\\simz1_thesis_maps_v2.py`','']
    if pub.spatial_coverage:
        text+=['## Cobertura de los mapas de flujo y presencia','',
               'Intervalos semiabiertos `[0,86400)`: la integral espacial se concilia con los censos nativos. El instante exacto del corte se informa separado; no genera duración adicional ni una hora 24.','',
               '| Corrida | Entradas a enlace antes del corte | Vehículo-segundos nativos | Vehículo-segundos sin asociación | Activos al corte sin enlace representado |',
               '|---|---:|---:|---:|---:|']
        for r in pub.spatial_coverage:
            text.append(f"| {r['scenario']} | {int(r['entries'])} | {r['native_vehicle_seconds']:.0f} | {r['unassociated_vehicle_seconds']:.0f} | {r['unassociated_at_cut']} |")
        text+=['','La tabla conserva 14 vehículos sin enlace representado exactamente a 86400 s en Run10K. No se asignan a una ubicación inventada. Las zonas grises en el mapa corresponden a enlaces sin fila publicada, no a una ocupación corporal ni una cola nula demostrada.','']
    (pub.out/'README.md').write_text('\n'.join(text),encoding='utf-8')
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'graficas_tesis_v2/mapas-red-vial')
    parser.add_argument('--spatial-dir',type=Path,default=ROOT/'graficas_tesis_v2/datos-espaciales')
    args=parser.parse_args(argv)
    out=args.output.resolve()
    if out.is_relative_to(ROOT/'scenarios'):
        raise ValueError('Thesis maps must not write into native scenarios')
    out.mkdir(parents=True,exist_ok=True)
    runs=load_runs()
    n,l,crs=read_network(runs[0]['network']);n2,l2,crs2=read_network(runs[1]['network'])
    if (n,l,crs)!=(n2,l2,crs2):
        raise ValueError('Different native networks require separate structural maps')
    for kind in ('lanes','signals','signal_control'):
        if sha(runs[0][kind])!=sha(runs[1][kind]):
            raise ValueError('Different '+kind+' inputs require separate maps')
    write_csv(out/'network-links.csv',l.values());write_csv(out/'network-nodes.csv',n.values())
    pairs=select_ab(runs,l,out)
    pub=MapPublisher(out,runs,n,l,crs)
    structures(pub,runs,pairs)
    if args.spatial_dir:
        spatial_maps(pub,args.spatial_dir.resolve())
    manifest=finalize(pub,runs,osm_comparison(runs))
    print(json.dumps(dict(status='generated',figures=len(manifest['figures']),output=str(out))))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
