"""Single-entry, read-only-native thesis collection. Never launches simulation."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import textwrap
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from simz1_thesis import sha, read_json, write_json
from simz1_thesis_runs_v2 import ROOT, RUNS
from simz1_thesis_inventory_v2 import ensure_inventory
from contextlib import contextmanager

OUT=ROOT/'graficas_tesis_v2'
VERSION='simz1-thesis-collection-v2.2'
RUN_IDS={RUNS[0][0]:'simz1-9d15f07ccc134aa69c60fdcbc887ea3f',RUNS[1][0]:'simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9'}
ALLOWED_GROUPS=set(RUN_IDS)|{'comparacion-1k-vs-10k-v8'}


@contextmanager
def collection_lock():
    """OS-owned exclusive writer lock; exit releases ownership, no stale PID guess."""
    path=OUT/'.collection.lock';handle=path.open('a+b')
    if path.stat().st_size==0:handle.write(b'1');handle.flush()
    handle.seek(0)
    if os.name=='nt':
        import msvcrt
        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            handle.close();raise RuntimeError('Another thesis collection writer holds the package lock')
        try:yield
        finally:
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1);handle.close()
    else:
        import fcntl
        try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close();raise RuntimeError('Another thesis collection writer holds the package lock')
        try:yield
        finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN);handle.close()


def relative(path,base=OUT):
    return Path(os.path.relpath(Path(path).resolve(),base.resolve())).as_posix()


def native_integrity():
    before=read_json(OUT/'logs/native-before.json');changed=[]
    for path,expected in before.items():
        p=ROOT/path
        if not p.is_file():changed.append(dict(path=path,reason='missing'));continue
        st=p.stat()
        if st.st_size!=expected['bytes'] or st.st_mtime_ns!=expected['mtime_ns']:
            changed.append(dict(path=path,reason='size_or_mtime_changed'))
        elif expected.get('sha256') and sha(p)!=expected['sha256']:
            changed.append(dict(path=path,reason='sha256_changed'))
    current={str(p.relative_to(ROOT)) for _,native in RUNS for p in (ROOT/'scenarios/zona1/montecarlo'/native).rglob('*') if p.is_file()}
    added=sorted(current-set(before))
    report=dict(status='passed' if not changed and not added else 'failed',files_checked=len(before),
        small_file_sha256_checks=sum('sha256' in v for v in before.values()),changed=changed,added=added,
        scope='All native run files: size/mtime; SHA256 for files <=2 MiB from initial snapshot. Consumed tables, native manifests and spatial source identities separately verified by generators. Multi-GB events/replay not rehashed by this final check.')
    if changed or added:raise ValueError('Native run changed: '+json.dumps(report))
    return report


def initial_native_snapshot():
    path=OUT/'logs/native-before.json'
    if path.exists():return
    records={}
    for _,native in RUNS:
        for p in (ROOT/'scenarios/zona1/montecarlo'/native).rglob('*'):
            if not p.is_file():continue
            s=p.stat();r=dict(bytes=s.st_size,mtime_ns=s.st_mtime_ns)
            if s.st_size<=2*1024*1024:r['sha256']=sha(p)
            records[str(p.relative_to(ROOT))]=r
    write_json(path,records)


def figures():
    result=[]
    inventory=read_json(OUT/'auditoria-existente.json')
    previous={Path(r['path']).as_posix():r for r in inventory['figures']}
    for manifest in sorted(OUT.rglob('figures-manifest.json')):
        group=manifest.relative_to(OUT).parts[0]
        if group not in ALLOWED_GROUPS:continue
        if any(p.startswith('.') for p in manifest.relative_to(OUT).parts):continue
        data=read_json(manifest)
        expected={RUN_IDS[group]} if group in RUN_IDS else set(RUN_IDS.values())
        if {i['run_id'] for i in data['identities']}!=expected or any(i['iteration']!=0 for i in data['identities']):
            raise ValueError('Collection contains an unrequested native identity: '+str(manifest))
        for record in data['figures']:
            stem=record['stem'];meta=read_json(manifest.parent/(stem+'.json'));details=meta['metadata']
            png=manifest.parent/(stem+'.png');old=previous.get(relative(png,ROOT),{})
            sources=[]
            for s in meta.get('sources',[]):
                if not Path(s['path']).is_file():raise ValueError('Missing figure source: '+s['path'])
                if s.get('sha256') and sha(s['path'])!=s['sha256']:raise ValueError('Changed figure source: '+s['path'])
                sources.append(dict(path=relative(s['path']),sha256=s.get('sha256'),kind=s.get('kind')))
            files=[]
            for item in record['files']:
                path=manifest.parent/item['path']
                if sha(path)!=item['sha256']:raise ValueError('Figure hash mismatch: '+str(path))
                files.append(dict(path=relative(path),sha256=item['sha256'],bytes=path.stat().st_size))
            objective=old.get('objective_ids') or details.get('objective') or record.get('objective')
            limits=details.get('limitations') or details.get('limitation') or old.get('limitation') or details.get('exclusions')
            if not limits:limits='Estadística descriptiva de una corrida sintética; no identifica causalidad ni calibración. Definiciones y exclusiones en JSON.'
            result.append(dict(stem=stem,group=manifest.relative_to(OUT).parts[0],title=details.get('title') or old.get('variable') or stem.replace('_',' '),
                objective=objective,variable=details.get('variable') or old.get('variable') or details.get('title') or stem.replace('_',' '),
                calculation=details.get('calculation') or details.get('calculation_rule') or old.get('calculation'),
                interpretation=details.get('interpretation') or old.get('utility') or 'Descripción del escenario y cohorte indicados en los ejes; comparar con su denominador y estado de completitud.',
                limitations=limits,sources=sources,identities=meta.get('identities'),files=files,origin='preserved' if old else 'new'))
    maps=OUT/'mapas-red-vial/manifest.json'
    data=read_json(maps)
    for record in data['figures']:
        if {i['run_id'] for i in record['identity']}!=set(RUN_IDS.values()) or any(i['iteration']!=0 for i in record['identity']):
            raise ValueError('Map contains an unrequested identity')
        files=[dict(path=relative(maps.parent/name),sha256=sha(maps.parent/name),bytes=(maps.parent/name).stat().st_size) for name in record['files'].values()]
        result.append(dict(stem=record['name'],group='mapas-red-vial',title=record['title'],objective=record['objective'],variable=record['variable'],
            calculation=record['calculation'],interpretation=record['interpretation'],limitations=record['limitation'],
            sources=[dict(path=relative(ROOT/s['path']),sha256=s['sha256'],kind=s.get('kind')) for s in data['sources']],
            identities=record['identity'],files=files,origin='new'))
    return result


def selection(records):
    requests=[('mapas-red-vial','mapa_01_red_base','red_base_z1'),
        ('mapas-red-vial','mapa_03_enlaces_dirigidos','red_enlaces_dirigidos'),
        ('mapas-red-vial','mapa_04_carriles','carriles_modelados'),
        ('mapas-red-vial','mapa_06_semaforos','semaforos'),
        ('mapas-red-vial','mapa_09_flujo_run1000','flujo_run1000'),
        ('mapas-red-vial','mapa_09_flujo_run10000','flujo_run10k'),
        ('comparacion-1k-vs-10k-v8','comparacion_tiempos_por_tipo','tiempos_1k_vs_10k'),
        ('comparacion-1k-vs-10k-v8','comparacion_distribuciones_tiempos','distribucion_1k_vs_10k'),
        ('comparacion-1k-vs-10k-v8','comparacion_descomposicion_tiempos','espera_y_tiempo_en_red'),
        ('comparacion-1k-vs-10k-v8','comparacion_activos_maximos','activos_y_acumulacion_global'),
        ('comparacion-1k-vs-10k-v8','comparacion_transporte_publico','transporte_publico'),
        (RUNS[1][0],'carga_rutas_ventanas','carga_recorridos_run10k'),
        ('mapas-red-vial','mapa_08_candidatos_ab','pares_ab_observados'),
        ('comparacion-1k-vs-10k-v8','comparacion_tiempos_ab_observados','tiempos_ab_1k_vs_10k'),
        (RUNS[1][0],'acumulacion_enlaces_criticos','acumulacion_critica_run10k'),
        (RUNS[1][0],'flujo_secciones_por_hora','flujo_secciones_run10k'),
        ('comparacion-1k-vs-10k-v8','comparacion_carga_espera_censura','censura_y_completitud'),
        ('comparacion-1k-vs-10k-v8','comparacion_composicion_trafico','composicion_configurada')]
    dest=OUT/'figuras-seleccionadas-tesis';dest.mkdir(exist_ok=True);selected=[]
    for idx,(group,stem,name) in enumerate(requests,1):
        matches=[r for r in records if r['group']==group and r['stem']==stem]
        if len(matches)!=1:raise ValueError(f'Missing/ambiguous curated figure: {group}/{stem}')
        original=matches[0];entry=dict(number=idx,name=f'fig_{idx:02d}_{name}',title=original['title'],selected_from=original['files'][0]['path'],files=[])
        for f in original['files']:
            source=OUT/f['path'];target=dest/(entry['name']+source.suffix);shutil.copy2(source,target)
            entry['files'].append(dict(path=relative(target),sha256=sha(target),bytes=target.stat().st_size))
        selected.append(entry)
    lines=['# Selección de figuras para tesis','','Copias verificadas de la colección. Los JSON conservan identidad, cálculo y procedencia originales. Para conclusiones, usar conjuntamente tiempos, censuras y cobertura.','',
           '| Figura | Título | Archivos |','|---|---|---|']
    for r in selected:
        links=' · '.join(f'[{Path(f["path"]).suffix[1:].upper()}]({Path(f["path"]).name})' for f in r['files'])
        lines.append(f'| {r["name"]} | {r["title"]} | {links} |')
    (dest/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write_json(dest/'manifest.json',dict(version=VERSION,figures=selected))
    return selected


def prose(value):
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False)
    return str(value or 'Consultar definición en el JSON asociado.')


def write_index(records,selected,inventory):
    lines=['# SIMZ1 — Gráficas de tesis v2: Run1000 y Run10K','',
        'Colección consolidada obtenida exclusivamente de las dos corridas v8, iteración 0, ventana nativa 0–86400 s. No se ejecutó MATSim/QSim, Validate ni DryRun. Las corridas, sus entradas, eventos, análisis y recibos se preservan.','',
        '**Lectura recomendada:** [selección de 18 figuras](figuras-seleccionadas-tesis/README.md). Cada figura de la colección final tiene PNG de 300 dpi, SVG vectorial y CSV/JSON de respaldo. El inventario inicial de 42 figuras distingue los 22 productos previos de Run1000 y los 10 PNG analíticos de cada corrida; esos 20 PNG originales se catalogan como antecedentes y no tienen todos los formatos nuevos. Las láminas QA no se cuentan como resultados.','',
        '| Etiqueta | LaunchId | Run ID | Estado |','|---|---|---|',
        '| Run1000 | a32f15487b1a49ac910ba799175658ca | simz1-9d15f07ccc134aa69c60fdcbc887ea3f | completed/valid; screening_pass |',
        '| Run10K | e496c091b9ef46ee9ca381576135e299 | simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9 | completed/valid recuperado; screening_pass |','',
        'El gateway original de Run10K conserva `running/simulation_and_analysis` y un `finished_utc` histórico. El cierre vigente consta en [recovery-receipt.json](../runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/recovery-receipt.json). No se corrige esa evidencia ni se promueve otra escala.','',
        '## Definiciones para interpretar las figuras','',
        '- **N = 1,000 / 10,000:** vehículos no públicos: 440/4,400 carros, 550/5,500 motos y 10/100 camiones. La flota pública permanece en 269 buses y 13,261 expediciones programadas. No se multiplica toda la oferta por diez.',
        '- **Tiempo completo:** llegada menos solicitud nativa de salida. Incluye espera de incorporación. Tiempo en red: llegada menos entrada al tráfico. En buses, el retraso entre hora programada e inicio nativo no se incluye en ese tiempo completo.',
        '- **Censura:** 2 privados en 1K y 200 en 10K no completan antes del corte. Los percentiles de completos excluyen esas observaciones; no representan la distribución incondicional de todas las solicitudes. Abortos administrativos al cierre se separan de abortos previos.',
        '- **Activos:** IDs físicos con intervalo entrada–salida vigente. Las medias horarias integran ese conteo; el pico es simultáneo, no suma de picos por familia. Expediciones no iniciadas no son buses circulantes.',
        '- **Flujo espacial:** incrementos de LinkEnter, por enlace y hora. VehicleEntersTraffic queda aparte. Se elige el enlace de mayor flujo conjunto dentro de cada vía con nombre OSM y luego las cuatro vías con mayor sección representativa. No se suman enlaces sucesivos para inventar un aforo de corredor.',
        '- **Frontera de las 24 h:** Run10K registra 1,252,416 transiciones nativas incluidas al corte. El replay representa 1,252,402 LinkEnter en [0,86400): las 14 restantes ocurren exactamente a 86400 y no tienen intervalo posterior de duración positiva. El censo sí identifica sus enlaces receptores. La diferencia coincide con los 14 activos sin intervalo espacial al corte; no son transiciones perdidas dentro de las horas graficadas. [Comprobación del corte](datos-espaciales/cut-boundary-review.json).',
        '- **Acumulación espacial:** asociación nativa de un vehículo a un enlace, integrada en segundos-vehículo. Es proxy por enlace; no mide posición corporal, longitud de cola, ocupación exacta de una intersección ni espera semafórica. Las integrales asociada y nativa coinciden en [0,86400): 6,003,954 s-veh en 1K y 14,339,608 s-veh en 10K; el contraste horario está en `datos-espaciales/*/coverage_hourly.csv`. Exactamente al corte 86400, 10K tiene 102 activos y 14 sin enlace representado: constan aparte en `datos-espaciales/run10000/manifest.json`, campo `totals.unassociated_at_cut`. No se imputan esos enlaces.',
        '- **Comparación:** descriptiva, una realización por carga. Semillas, composición proporcional, política y red modelada son comunes. Los XML de horarios difieren en metadatos de N y hash de política; se comprobó igualdad semántica del servicio, preservando el rechazo del comparador estricto y los hashes originales en `compatibility.json`.',
        '- **Geometría:** local aproximada; no cartografía GIS verificada. El `map.osm` indicado en la raíz no existe; se usa `scenarios/zona1/map.osm` y principalmente la red de salida nativa. Atribución: © OpenStreetMap contributors (ODbL), según copia local.',
        '', '## Evidencia A–B','',
        'No se identificó una pareja única A–B preespecificada para la tesis. Los viajes privados sí conservan enlaces de salida y llegada observados. La metodología reproducible selecciona pares comunes entre completos de ambas cargas, ordena por `min(n1K,n10K)` descendente, desempata por IDs y toma cuatro. Los tamaños de muestra son 36/273, 32/356, 26/231 y 26/290. Se publican todos los candidatos comunes y observaciones usadas en `mapas-red-vial/ab-*.csv`.','',
        'La figura comparativa A–B calcula media, mediana, p90 y p95 de llegada menos salida nativa para cada par. Los extremos son observables; la selección es exploratoria posterior a los resultados y no impone una ruta fija entre ellos. Las censuras por OD declarado se informan por separado cuando corresponden, sin inventar destinos de llegada. No se mide tiempo puerta a puerta fuera del dominio.','',
        '## Auditoría de las figuras existentes antes de esta tarea','',
        '| Figura y ubicación original | Objetivo | Variable y utilidad | Fuente | Cálculo | Limitación |','|---|---|---|---|---|---|']
    def cell(value):return prose(value).replace('|','/').replace('\n',' ')
    for r in inventory['figures']:
        src='; '.join(f'[{Path(s["path"]).name}](../{s["path"]})' for s in r['sources'])
        lines.append(f'| [{r["run"]}: {r["figure"]}](../{r["path"]}) | {cell(r["objective_ids"])} | {cell(r["variable"])}. {cell(r["utility"])} | {src} | {cell(r["calculation"])} | {cell(r["limitation"])} |')
    lines+=['','Las brechas iniciales eran mapas, flujo y acumulación espacial, métricas comunes de todas las familias, comparativas y A–B medido. Se cubren con los productos nuevos descritos abajo; los gráficos originales redundantes se conservan como antecedente y no todos pasan a la selección curada.','',
            '## Catálogo final por figura','']
    for group in dict.fromkeys(r['group'] for r in records):
        lines += [f'### {group}','']
        for r in (x for x in records if x['group']==group):
            links=' · '.join(f'[{Path(f["path"]).suffix[1:].upper()}]({f["path"]})' for f in r['files'])
            src='; '.join(f'[{Path(s["path"]).name}]({s["path"]})' for s in r['sources'])
            lines += [f'#### {r["stem"]} — {r["title"]}','',links,'',f'**Qué muestra / objetivo:** {prose(r["variable"])}. {prose(r["objective"])}.',
                      '',f'**Cómo se calculó:** {prose(r["calculation"])}','',f'**Interpretación:** {prose(r["interpretation"])}','',f'**Limitaciones:** {prose(r["limitations"])}','',f'**Fuentes:** {src}.','']
    lines += ['## Reproducibilidad','',
        'Desde PowerShell externa, en la raíz del repositorio:','',
        '```powershell','.\scripts\generate_thesis_graphs_v2.ps1','```','',
        'Verifica fuentes y reutiliza el extracto espacial verificado. Si falta, lo reconstruye una vez desde SQLite existente. Conserva los 22 gráficos históricos de Run1000; genera el núcleo equivalente de Run10K y las extensiones, mapas, comparativas e índice. `-ForceFigures` fuerza el render del núcleo Run10K y complementos. `-VerifyOnly` verifica la entrega existente sin renderizar. No llama lanzadores de simulación.','',
        'Scripts nuevos: [entrada PowerShell](../scripts/generate_thesis_graphs_v2.ps1), [integración](../python/simz1_thesis_collection_v2.py), [inventario](../python/simz1_thesis_inventory_v2.py), [métricas espaciales](../python/simz1_thesis_link_metrics_v2.py), [figuras por corrida](../python/simz1_thesis_runs_v2.py), [figuras espaciales por corrida](../python/simz1_thesis_run_spatial_v2.py), [mapas](../python/simz1_thesis_maps_v2.py) y [comparativas](../python/simz1_thesis_compare_v2.py). Se reutilizan los módulos previos `simz1_thesis*` y `simz1_aggregate_replay` sin modificarlos.','',
        'Seguimiento de solo lectura:','',
        '```powershell',"Get-Content -Encoding UTF8 .\graficas_tesis_v2\verification.json", "Get-Content -Encoding UTF8 .\graficas_tesis_v2\logs\collection-progress.json",'```','',
        '## Cobertura de objetivos','',
        '| Objetivo | Evidencia que sí aporta esta colección | Cobertura parcial / no demostrada | Trabajo futuro recomendado |','|---|---|---|---|',
        '| General: estimar tiempo entre A y B | Cuatro pares de enlaces observados comunes, tamaños de muestra, cuantiles, mapas y descomposición de espera/tiempo en red; datos individuales reproducibles | Selección exploratoria, rutas realizadas pueden diferir; sólo completos; no validación empírica ni predicción calibrada para cualquier A–B | Predefinir pares representativos, recolectar tiempos reales, replicar semillas y cuantificar incertidumbre/censura |',
        '| OE1: modelar red vial | Mapas base, nodos, enlaces, sentidos, carriles, velocidad configurada y sistemas semafóricos; tablas de atributos y hashes de red realmente utilizada | No acredita exactitud GIS, número real de carriles o calibración de ciclos; conectores/atributos procesados difieren del extracto OSM | Levantamiento y contraste de longitudes, sentidos, carriles y planes semafóricos con observaciones |',
        '| OE2: influencia de demanda, señales, composición y externos | Comparación descriptiva 1K–10K con oferta pública constante, tiempos, espera, censura, flujo y acumulación; separación de familias y horarios | Las señales, proporciones y condiciones externas no se varían independientemente; no se identifica su efecto causal; una semilla por carga | Diseño factorial con demanda, ciclos, composición e incidentes/clima y réplicas, manteniendo controles y fuentes observadas |',
        '| OE3: métricas cuantitativas | Media/mediana/p90/p95, ECDF/cajas, flujo por secciones, acumulación por enlace y hora, máximos, servicio de buses y carga; respaldos verificables | Acumulación es proxy de enlace, no cola corporal ni intersección medida; utilización de buses es operación de flota, no pasajeros; variación espacial no es trayectoria continua exacta | Aforos/colas observados, seguimiento corporal validado, datos de pasajeros y rutas A–B preespecificadas |','',
        'La aceptación técnica de las dos corridas permanece separada de la calibración y de cualquier autorización de nuevas simulaciones.']
    (OUT/'INDICE_GENERAL.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def verify(records,selected):
    count=0;sources={}
    for row in records+selected:
        if 'group' in row and row['group'] not in ALLOWED_GROUPS|{'mapas-red-vial'}:
            raise ValueError('Historical figure excluded from current collection: '+row['group'])
        for source in row.get('sources',[]):
            if source.get('sha256'):
                previous=sources.get(source['path'])
                if previous and previous!=source['sha256']:raise ValueError('Contradictory source hashes')
                sources[source['path']]=source['sha256']
        suffixes=set()
        for f in row['files']:
            path=OUT/f['path'];suffixes.add(path.suffix)
            if sha(path)!=f['sha256']:raise ValueError('Artifact hash mismatch: '+str(path))
            if path.suffix=='.png':
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    if min(im.size)<500:raise ValueError('Unexpected small figure')
            elif path.suffix=='.svg':ET.parse(path)
            elif path.suffix=='.json':read_json(path)
            count+=1
        if suffixes!={'.png','.svg','.csv','.json'}:raise ValueError('Incomplete artifact family')
    for path,digest in sources.items():
        if not (OUT/path).is_file() or sha(OUT/path)!=digest:raise ValueError('Missing/changed source: '+path)
    native=native_integrity()
    result=dict(status='passed',version=VERSION,verified_utc=datetime.now(timezone.utc).isoformat(),
        unique_scientific_figures=len(records),selected_copies=len(selected),artifacts_checked=count,source_hashes_checked=len(sources),native_integrity=native,
        visual_qa='Mechanical verification covers every PNG/SVG/CSV/JSON. Recorded visual inspections are in logs/visual-review.json when present.',
        simulation_rerun=False)
    write_json(OUT/'verification.json',result)
    for group in sorted({r['group'] for r in records if 'group' in r}):
        group_rows=[r for r in records if r.get('group')==group]
        local=dict(status='passed',version=VERSION,verified_utc=result['verified_utc'],
            figure_count=len(group_rows),file_count=sum(len(r['files']) for r in group_rows),
            files=[dict(f,path=relative(OUT/f['path'],OUT/group)) for r in group_rows for f in r['files']],
            visual_evidence='../logs/visual-review.json',verification_scope='Every listed hash, PNG decode, SVG XML and JSON validated by the collection verifier; native integrity unchanged.')
        write_json(OUT/group/'collection-verification.json',local)
        if group in ('mapas-red-vial','comparacion-1k-vs-10k-v8'):
            write_json(OUT/group/'artifact-verification.json',local)
    return result


def contact_sheets(selected):
    folder=OUT/'logs';font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
    for page,start in enumerate(range(0,len(selected),6),1):
        canvas=Image.new('RGB',(1800,1500),'white');draw=ImageDraw.Draw(canvas)
        for slot,item in enumerate(selected[start:start+6]):
            png=next(OUT/f['path'] for f in item['files'] if f['path'].endswith('.png'))
            with Image.open(png) as im:
                im=im.convert('RGB');im.thumbnail((880,440));x=(slot%2)*900+(900-im.width)//2;y=(slot//2)*500+40;canvas.paste(im,(x,y))
            draw.text(((slot%2)*900+10,(slot//2)*500+10),item['name'],fill='#0f172a',font=font)
        canvas.save(folder/f'seleccion-contacto-{page}.jpg',quality=92)


def integrate():
    inventory=ensure_inventory(ROOT);records=figures();selected=selection(records)
    for folder,_ in RUNS:
        rows=[r for r in records if r['group']==folder]
        lines=['# Colección de figuras de esta corrida','',
            'Iteración 0, ventana 0–24 h. [Índice general y cobertura de objetivos](../INDICE_GENERAL.md).',
            'Los antecedentes se conservan; complementos amplían familias y espacial añade flujo/acumulación desde el replay existente.','',
            '| Figura | Qué muestra | Método y límite |','|---|---|---|']
        for r in rows:
            files=' · '.join(f'[{Path(f["path"]).suffix[1:].upper()}]({relative(OUT/f["path"],OUT/folder)})' for f in r['files'])
            lines.append(f'| {r["stem"]}<br>{files} | {prose(r["variable"]).replace(chr(124),"/")} | {prose(r["calculation"]).replace(chr(124),"/")}<br>{prose(r["limitations"]).replace(chr(124),"/")} |')
        (OUT/folder/'INDICE_COLECCION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    implementations=[dict(path=relative(p),sha256=sha(p)) for p in sorted((ROOT/'python').glob('simz1_thesis*_v2.py'))]
    implementations.append(dict(path='../scripts/generate_thesis_graphs_v2.ps1',sha256=sha(ROOT/'scripts/generate_thesis_graphs_v2.ps1')))
    manifest=dict(schema=VERSION,created_utc=datetime.now(timezone.utc).isoformat(),native_runs=inventory['identities'],
        initial_inventory=inventory,figures=records,curated=selected,counts=dict(Counter(r['group'] for r in records)),implementation=implementations,
        native_run_mutation=False,simulation_rerun=False,iteration=0,horizon_seconds=[0,86400],
        scope='Only two requested v8 run folders, comparison and maps. Other pre-existing thesis history folders remain untouched and excluded.',
        source_fingerprint_policy='Producer fingerprints preserved. New postprocessing hashes are separate; next simulation must pass the existing dependency fingerprint mechanism.')
    write_index(records,selected,inventory);write_json(OUT/'manifest.json',manifest);contact_sheets(selected)
    result=verify(records,selected)
    print(json.dumps(dict(status=result['status'],figures=len(records),selected=len(selected),counts=manifest['counts']),ensure_ascii=False),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--force-figures',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--integrate-only',action='store_true');a=p.parse_args()
    (OUT/'logs').mkdir(exist_ok=True,parents=True);initial_native_snapshot();native_integrity()
    if a.verify_only:
        manifest=read_json(OUT/'manifest.json');print(json.dumps(verify(manifest['figures'],manifest['curated'])));return
    if not a.integrate_only:
        from simz1_thesis_link_metrics_v2 import generate as extract
        from simz1_thesis_runs_v2 import generate as runs
        from simz1_thesis_maps_v2 import main as maps
        from simz1_thesis_compare_v2 import generate as compare
        from simz1_thesis_run_spatial_v2 import generate as spatial
        phases=[('inventory',lambda:ensure_inventory(ROOT)),('spatial_extract',lambda:extract(OUT/'datos-espaciales')),
            ('per_run',lambda:runs(OUT,a.force_figures)),('maps',lambda:maps(['--output',str(OUT/'mapas-red-vial'),'--spatial-dir',str(OUT/'datos-espaciales')])),
            ('comparison',lambda:compare(OUT/'comparacion-1k-vs-10k-v8',OUT/'datos-espaciales')),('per_run_spatial',lambda:spatial(OUT))]
        for name,action in phases:
            write_json(OUT/'logs/collection-progress.json',dict(phase=name,status='running',utc=datetime.now(timezone.utc).isoformat()))
            print('PHASE '+name,flush=True);action()
    integrate()
    write_json(OUT/'logs/collection-progress.json',dict(phase='complete',status='passed',utc=datetime.now(timezone.utc).isoformat()))


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with collection_lock():main()
