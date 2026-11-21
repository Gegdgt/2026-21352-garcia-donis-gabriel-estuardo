"""Presentación aislada de productos SimZ1 ya publicados; nunca ejecuta MATSim.

python simz1_thesis.py individual --run-dir PATH --iteration 0 --output NEW_ROOT
python simz1_thesis.py compare --run PATH 0 --run OTHER 0 --output NEW_ROOT
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

VERSION = 'simz1-graficas-tesis-v2.1'
BASE = Path(__file__).resolve().parent


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value):
    if isinstance(value, dict):
        for item in value.values(): finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value: finite(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Dato no finito: no se publica ni se convierte en cero')
    return value


def read_json(path):
    return finite(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def write_json(path, data):
    Path(path).write_text(json.dumps(finite(data), ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n', encoding='utf-8')


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Archivo ausente/fuera de carpeta: ' + str(path))
    return path


def verified(root, record):
    path = contained(root, record['path'])
    if sha(path) != record['sha256']:
        raise ValueError('SHA256 incompatible: ' + str(path))
    if 'size_bytes' in record and path.stat().st_size != record['size_bytes']:
        raise ValueError('Tamaño incompatible: ' + str(path))
    return path


def records(value):
    """Records, including historical versions retained by the native manifest."""
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            yield (value['path'], value['sha256'])
        for child in value.values(): yield from records(child)
    elif isinstance(value, list):
        for child in value: yield from records(child)


def identity_check(value, run_id, iteration, context):
    if value.get('run_id') != run_id or value.get('iteration') != iteration:
        raise ValueError('Identidad Run ID/iteración incompatible: ' + context)


def csv_rows(path, limit=200000):
    """Only aggregate CSVs; agent-sized tables are streamed by their consumers."""
    result = []
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if len(result) >= limit:
                raise ValueError('Tabla agregada supera límite; requiere agregación incremental: ' + str(path))
            item = {}
            for key, value in row.items():
                if value in ('', 'sin datos', 'None', 'null'): item[key] = None
                elif re.fullmatch(r'-?\d+', value): item[key] = int(value)
                elif value in ('True','False'): item[key] = value=='True'
                else:
                    try: parsed = float(value)
                    except ValueError: item[key] = value
                    else: item[key] = finite(parsed)
            result.append(item)
    return result


def configured_n(manifest):
    counts = manifest.get('counts', {})
    value = counts.get('non_public_vehicles_configured')
    # Historical manifests explicitly describe private + freight populations.
    if value is None and all(k in counts for k in ('private_vehicles_configured', 'freight_vehicles_configured')):
        value = counts['private_vehicles_configured'] + counts['freight_vehicles_configured']
    if type(value) is not int or value < 1:
        raise ValueError('N no públicos no está definido inequívocamente en el manifiesto')
    stated = manifest.get('experiment', {}).get('total_non_public_vehicles')
    if stated is not None and stated != value: raise ValueError('N contradice el experimento')
    return value


def load_bundle(run_dir, iteration, diagnostic=False):
    run = Path(run_dir).resolve()
    if 'latest-successful' in str(run).lower(): raise ValueError('Se requiere RunDir explícito')
    native_path = run / 'run-manifest.json'
    native = read_json(native_path)
    if native.get('schema_version') != 1 or Path(native.get('folder', '')).resolve() != run:
        raise ValueError('Manifest/carpeta incompatible')
    rid = native.get('run_id')
    if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', rid):
        raise ValueError('Run ID inválido')
    official = native.get('status') == 'completed' and native.get('validation', {}).get('status') == 'valid'
    if not official and not diagnostic: raise ValueError('Se requiere completed/valid; sólo diagnóstico separado para prefijos')
    if not official and native.get('status') not in ('failed', 'interrupted', 'incomplete', 'aborted'):
        raise ValueError('No se leen corridas preparadas o activas; preservar sus escritores')
    completed = native.get('iterations', {}).get('completed', [])
    if official and iteration not in completed: raise ValueError('Iteración no completada')
    result = native.get('results', {}).get(str(iteration))
    if result is None: raise ValueError('Iteración sin evidencia nativa')
    publication = 'diagnostic_prefix' if diagnostic else 'official'
    horizon = native.get('time_horizon', {})
    if not all(isinstance(horizon.get(k), (int, float)) for k in ('start_seconds', 'end_seconds')):
        raise ValueError('Horizonte ausente')
    if horizon['end_seconds'] <= horizon['start_seconds']: raise ValueError('Horizonte inválido')
    coverage = result.get('observed_event_end_seconds')
    if diagnostic and (coverage is None or coverage <= 0):
        raise ValueError('Prefijo sin cobertura observada verificable')
    identity = dict(run_id=rid, launch_id=native.get('launch_id'), iteration=iteration,
        N_configured=configured_n(native), counts=native.get('counts', {}),
        composition=native.get('demand_composition'), horizon=horizon,
        seeds=dict(demand=native.get('demand_seed'), matsim=native.get('matsim_seed')),
        manifest_sha256=sha(native_path), native_status=native.get('status'),
        scenario_version=native.get('scenario_version'), scenario_base_version=native.get('scenario_base_version'),
        observation_policy=native.get('experiment',{}).get('observation_policy'),
        configuration=dict(admission_execution=native.get('admission_execution'),
            temporal_policy=native.get('temporal_policy'),signal_variant=native.get('signal_variant'),
            origin_policy=native.get('origin_policy'),destination_policy=native.get('destination_policy'),
            public_service_date=native.get('experiment',{}).get('service_date')),
        native_validation=native.get('validation', {}).get('status'),
        publication_status=publication, observed_coverage_seconds=coverage,
        iterations=native.get('iterations'), run_directory=str(run))
    bundle = dict(identity=identity, manifest=native, run_dir=run, sources=[], pending=[])
    def source(path, kind, verification):
        bundle['sources'].append(dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size,
                                      kind=kind, verification=verification))
        return path
    source(native_path, 'native_manifest', 'completed/valid and exact iteration' if official else 'observed incomplete prefix')
    analysis_dir = run / 'analysis' / f'it.{iteration}'
    ap, sp = analysis_dir / 'analysis-manifest.json', analysis_dir / 'analysis-status.json'
    analyzed, status = read_json(ap), read_json(sp)
    for name, value in [('analysis-manifest', analyzed), ('analysis-status', status)]:
        identity_check(value, rid, iteration, name)
        if value.get('status') != 'completed': raise ValueError('Producto analítico no publicado: ' + name)
    if analyzed.get('fingerprint') != status.get('fingerprint') or status.get('manifest_sha256') != sha(ap):
        raise ValueError('Huella/recibo de análisis incompatible')
    native_records = set(records(native))
    for rec in analyzed.get('sources', {}).values():
        if (rec.get('path'), rec.get('sha256')) not in native_records:
            raise ValueError('Fuente analítica ajena al manifiesto nativo: ' + str(rec))
    source(ap, 'analysis_manifest', 'receipt SHA256 and native source references')
    source(sp, 'analysis_status', 'identity and fingerprint')
    artifacts = {}
    for rec in analyzed.get('artifacts', []):
        if rec['path'] in artifacts: raise ValueError('Artefacto duplicado')
        # Verify historical plots too: preservation is explicit, no replacements.
        artifacts[rec['path']] = verified(analysis_dir, rec)
    bundle['analysis_manifest'] = analyzed
    for rel, key in [('graficas_perfiles/resumen_perfiles.json', 'profile_report'),
                     ('graficas_perfiles/metricas_temporales.json', 'temporal_report')]:
        if rel in artifacts:
            data = read_json(artifacts[rel]); identity_check(data, rid, iteration, rel)
            bundle[key] = data; source(artifacts[rel], key, 'analysis artifact SHA256')
    if 'profile_report' not in bundle: raise ValueError('Falta resumen_perfiles publicado')
    provenance_path = artifacts.get('trips.csv.provenance.json')
    table_path = artifacts.get('trips.csv.gz')
    if provenance_path and table_path:
        provenance = read_json(provenance_path); identity_check(provenance, rid, iteration, 'trip provenance')
        if provenance.get('csv_sha256') != sha(table_path): raise ValueError('Tabla/procedencia incompatible')
        bundle['trips_path'] = source(table_path, 'canonical_trips', 'analysis hash, provenance hash and row identities')
        bundle['trip_provenance'] = provenance
        source(provenance_path, 'trip_provenance', 'analysis artifact SHA256')
    for rel, key in [('graficas_perfiles/flujo_ocupacion_15min.csv', 'temporal_rows'),
                     ('graficas_perfiles/cohortes_temporales.csv', 'cohort_rows')]:
        if rel in artifacts:
            bundle[key] = csv_rows(artifacts[rel]); source(artifacts[rel], key, 'analysis artifact SHA256')
    balanced_dir = analysis_dir / 'balanced-launch'
    if (balanced_dir / 'report.json').is_file():
        bp = balanced_dir / 'report.json'; balanced = read_json(bp)
        identity_check(balanced, rid, iteration, 'balanced-launch')
        if balanced.get('manifest_sha256') != identity['manifest_sha256'] or balanced.get('events') != result.get('events'):
            raise ValueError('Balanced-launch no corresponde al manifiesto/eventos de esta corrida')
        if balanced.get('status') != 'verified_observations': raise ValueError('Balanced-launch no verificado')
        if balanced.get('day_observation') and balanced['day_observation'] != result.get('day_observation'):
            raise ValueError('Censo balanced-launch incompatible')
        bundle['balanced_report'] = balanced
        source(bp, 'balanced_report', 'native manifest SHA256, events reference, census')
        for rel, digest in balanced.get('files', {}).items():
            path = verified(balanced_dir, dict(path=rel, sha256=digest))
            keys = {'hours-00-24.csv':'balanced_hours','day-groups.csv':'balanced_groups',
                    'freight-completion.csv':'freight_rows'}
            if rel in keys:
                bundle[keys[rel]] = csv_rows(path); source(path, keys[rel], 'balanced report SHA256')
    # Original exporter publishes one of these two layouts. Ambiguity is rejected.
    op_candidates = [analysis_dir / 'operational_report.json',
                     run / 'analysis' / 'prompt13' / f'it.{iteration}' / 'operational_report.json']
    found = [p for p in op_candidates if p.is_file()]
    if len(found) > 1: raise ValueError('Dos informes operativos: seleccione una publicación inequívoca')
    if found:
        op_path = found[0]; op = read_json(op_path)
        identity_check(op, rid, iteration, 'operational')
        if op.get('manifest_sha256') != identity['manifest_sha256']:
            bundle['pending'].append(dict(indicator='operational_timeline', reason='Informe operativo de otra revisión del manifiesto; conservado sin reutilizar'))
        else:
            for key, rec in op.get('source_records', {}).items():
                if key != 'progress_log' and (rec.get('path'), rec.get('sha256')) not in native_records:
                    raise ValueError('Fuente operacional incompatible: ' + key)
            bundle['operational_report'] = op
            source(op_path, 'operational_report', 'native manifest SHA256 and source references')
            ip = op_path.parent / 'progress_intervals.csv'
            hp = op_path.parent / 'operational_hourly.csv'
            if ip.is_file():
                intervals = csv_rows(ip)
                reconcile_intervals(intervals, op)
                # The legacy report did not hash companion CSVs. Verify their
                # exact clocks/gauges against the small instrumented log, never
                # against a replay or a fresh event analysis.
                log_record = op.get('source_records', {}).get('progress_log')
                if not log_record: raise ValueError('Informe operacional sin procedencia del log')
                log_path = verified(run, log_record)
                from simz1_operational_report import progress_log, hourly_metrics
                expected_intervals, _ = progress_log(log_path, iteration, result['native_qsim'])
                normalized = []
                for row in intervals:
                    row = dict(row)
                    if isinstance(row.get('wait_observation'), str):
                        row['wait_observation'] = ast.literal_eval(row['wait_observation'])
                    normalized.append(row)
                if normalized != expected_intervals:
                    raise ValueError('CSV operacional difiere de los intervalos/snapshots nativos publicados')
                bundle['operational_intervals'] = intervals
                source(log_path, 'native_progress_log', 'original report SHA256; streaming progress records reconciled to native manifest')
                source(ip, 'operational_intervals', 'every interval/gauge reconciled against original log and native progress totals')
            if hp.is_file():
                hourly = csv_rows(hp)
                if ip.is_file() and result.get('temporal_events'):
                    expected_hourly = hourly_metrics(result['temporal_events'], expected_intervals)
                    if hourly != expected_hourly: raise ValueError('Tabla horaria operacional no coincide con su fuente nativa')
                bundle['operational_hourly'] = hourly
                source(hp, 'operational_hourly', 'native temporal summary and verified progress intervals')
    network = result.get('network') or native.get('inputs', {}).get('network')
    if network:
        bundle['network_path'] = source(verified(run, network), 'network', 'native artifact SHA256')
    bundle['source_versions'] = dict(analysis_fingerprint=analyzed.get('fingerprint'),
        analysis_implementation=analyzed.get('specification', {}).get('implementation'),
        balanced_postprocessor=bundle.get('balanced_report', {}).get('postprocessor_version'))
    return bundle


def reconcile_intervals(rows, op):
    if not rows: raise ValueError('Serie operativa vacía')
    native = op.get('native', {}).get('progress', {})
    times = [row.get('time') for row in rows]
    if any(t is None for t in times) or times != sorted(set(times)):
        raise ValueError('Tiempos operativos no ordenados/duplicados')
    for key in ('link_transitions', 'arrivals', 'wait_signal', 'wait_storage', 'wait_priority',
                'wait_congestion', 'forced_moves'):
        field = key
        observed = [row[field] for row in rows if row.get(field) is not None]
        if observed and key in native and not math.isclose(sum(observed), native[key], abs_tol=1e-6):
            raise ValueError('CSV operacional contradice total nativo: ' + field)
        if any(value < 0 for value in observed): raise ValueError('Delta operacional negativo')


def style():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':13,
        'axes.labelsize':11,'legend.fontsize':9,'axes.spines.top':False,
        'axes.spines.right':False,'svg.fonttype':'none','savefig.dpi':300})


class Publisher:
    def __init__(self, directory, identities, sources, source_versions=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.identities = identities
        self.sources = sources
        self.source_versions = source_versions or {}
        self.figures = []
        self.pending = []

    def save(self, fig, stem, rows, metadata):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', stem) or stem in {f['stem'] for f in self.figures}:
            raise ValueError('Nombre de figura inseguro o repetido: ' + stem)
        rows = list(rows); finite(rows); finite(metadata)
        if any(i.get('publication_status') == 'diagnostic_prefix' for i in self.identities):
            fig.text(.5,.005,'DIAGNÓSTICO — prefijo observado; no representa una jornada completa',
                     ha='center', color='#a52a2a',fontsize=9)
        data = dict(schema_version=VERSION, figure=stem, identities=self.identities,
            source_versions=self.source_versions, sources=self.sources,
            units=metadata.get('units', metadata.get('unit')),
            filters=metadata.get('filters'), denominators=metadata.get('denominators', metadata.get('denominator')),
            calculation=metadata.get('calculation', metadata.get('calculation_rule')),
            observations=metadata.get('observations', metadata.get('n_observations')),
            exclusions=metadata.get('exclusions',metadata.get('n_excluded')), metadata=metadata, rows=rows)
        json_path = self.directory / (stem + '.json')
        write_json(json_path, data)
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with (self.directory / (stem+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields or ['status']);writer.writeheader()
            for row in rows:
                writer.writerow({k:json.dumps(v,ensure_ascii=False,allow_nan=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
        fig.savefig(self.directory / (stem+'.png'), dpi=300, bbox_inches='tight',
                    metadata={'Description':json.dumps({'version':VERSION,'figure':stem,'identities':self.identities},ensure_ascii=False)})
        fig.savefig(self.directory / (stem+'.svg'), bbox_inches='tight',
                    metadata={'Description':json.dumps({'version':VERSION,'figure':stem,'identities':self.identities},ensure_ascii=False)})
        plt.close(fig)
        files = [dict(path=stem+ext,sha256=sha(self.directory/(stem+ext))) for ext in ('.png','.svg','.csv','.json')]
        record = dict(stem=stem, objective=metadata.get('objective','Caracterización operativa y tiempos de viaje'),files=files)
        self.figures.append(record)
        return record

    def finish(self):
        for record in self.sources:
            if sha(record['path']) != record['sha256']:
                raise ValueError('Fuente cambió durante generación: '+record['path'])
        modules = {Path(module.__file__).resolve() for module in list(sys.modules.values())
                   if getattr(module,'__file__',None) and Path(module.__file__).resolve().parent == BASE
                   and Path(module.__file__).suffix == '.py'}
        modules.update(BASE.glob('simz1_thesis*.py'))
        code = [dict(path=p.name,sha256=sha(p)) for p in sorted(modules)]
        manifest = dict(schema_version=VERSION, created_utc=datetime.now(timezone.utc).isoformat(),
            package_role='isolated_graphics_revision_not_canonical_report_package',
            identities=self.identities, sources=self.sources, source_versions=self.source_versions,
            source_verification='Published summaries and consumed small artifacts; native event references matched to accepted manifest. No event rescan, replay, or new native validation.',
            implementation=code, environment=dict(python=sys.version,matplotlib=matplotlib.__version__),
            figures=self.figures, pending=self.pending)
        write_json(self.directory/'figures-manifest.json',manifest)
        lines=['# Índice de figuras', '', 'Versión de presentación aislada. No contiene interpretación científica.', '',
               '| Figura | Objetivo | Archivos |','|---|---|---|']
        for f in self.figures:
            s=f['stem'];lines.append(f'| {s} | {f["objective"]} | [PNG]({s}.png) · [SVG]({s}.svg) · [CSV]({s}.csv) · [JSON]({s}.json) |')
        if self.pending:
            lines += ['', '## Indicadores pendientes', '']
            lines += ['- '+(p if isinstance(p,str) else json.dumps(p,ensure_ascii=False)) for p in self.pending]
        (self.directory/'INDICE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return manifest


def safe_output(output, bundles):
    output = Path(output).resolve()
    for b in bundles:
        if output.is_relative_to(b['run_dir']):
            raise ValueError('Salida debe estar fuera de la carpeta de corrida y artefactos canónicos')
    return output


def attach_indicators(bundles, paths):
    from simz1_thesis_spatial import load_indicators
    for path in paths or []:
        header=read_json(path)
        matches=[b for b in bundles if (b['identity']['run_id'],b['identity']['iteration']) ==
                 (header.get('run_id'),header.get('iteration'))]
        if len(matches)!=1: raise ValueError('Paquete de indicadores no corresponde a una selección única')
        bundle=matches[0]
        if 'indicators' in bundle: raise ValueError('Paquete de indicadores repetido para corrida/iteración')
        bundle['indicators']=load_indicators(path,bundle)
        bundle['sources'].extend(bundle['indicators']['sources'])


def generate_individual(bundle, output):
    from simz1_thesis_profiles import render_profiles
    from simz1_thesis_operations import render_operations
    from simz1_thesis_spatial import render_spatial
    ident=bundle['identity']; root=safe_output(output,[bundle])
    destination=root/ident['publication_status']/ident['run_id']/f'it.{ident["iteration"]}'
    publisher=Publisher(destination,[ident],bundle['sources'],bundle['source_versions'])
    publisher.pending.extend(bundle['pending'])
    for render in (render_profiles,render_operations,render_spatial):
        report=render(bundle,publisher)
        if report: publisher.pending.extend(report.get('pending',[]))
    publisher.finish()
    return destination


def compatibility(bundles):
    if len(bundles)<2: raise ValueError('Comparación requiere dos selecciones explícitas o más')
    seen=set(); descriptors=[]
    for b in bundles:
        identity=b['identity']; key=(identity['run_id'],identity['iteration'])
        if key in seen: raise ValueError('Corrida/iteración repetida')
        seen.add(key)
        if identity['publication_status'] != 'official': raise ValueError('No mezclar prefijos diagnósticos con comparaciones oficiales')
        m=b['manifest']; report=b['profile_report']; inputs=m.get('inputs',{})
        structural={k:v['sha256'] for k,v in inputs.items() if
            ('network' in k or 'signal' in k or k in ('transit_schedule','transit_vehicles','input:freight-weekday/service.json'))}
        descriptors.append(dict(horizon=m.get('time_horizon'), canonical_definition=report.get('canonical_definition'),
            metric_definition=report.get('metric_definition'), filters=report.get('filters'),
            base_scenario_identity=m.get('experiment',{}).get('base_scenario_identity'),
            scenario_version=m.get('scenario_version'), scenario_base_version=m.get('scenario_base_version'),
            structural_inputs=structural, agent_catalog=m.get('agent_configuration',{}).get('sha256'),
            observation_policy=m.get('experiment',{}).get('observation_policy'),
            temporal_policy=m.get('temporal_policy'), demand_window=m.get('demand_window'),
            origin_policy=m.get('origin_policy'), destination_policy=m.get('destination_policy'),
            service_date=m.get('experiment',{}).get('service_date'),
            freight_policy=m.get('freight_completion_policy'),
            admission_policy_selection=m.get('admission_policy_selection'),
            short_link_signal_coordination=m.get('short_link_signal_coordination'),
            admission_execution=m.get('admission_execution'),
            composition_weights=m.get('demand_composition',{}).get('family_weights'),
            demand_definition={k:m.get('temporal_demand',{}).get(k) for k in
                ('profile','trips_per_person','hourly_weights','hourly_probabilities','type_schedules','demand_window','departure_intervals','observation_policy')}))
    differing=[k for k in descriptors[0] if any(d[k]!=descriptors[0][k] for d in descriptors[1:])]
    if differing: raise ValueError('Corridas incompatibles; no se publica comparación: '+', '.join(differing))
    return dict(checked=descriptors[0], identities=[b['identity'] for b in bundles],
        seeds_differ=len({json.dumps(b['identity']['seeds'],sort_keys=True) for b in bundles})>1,
        interpretation='Comparación descriptiva; no atribuye causalidad a N. Semillas y versiones se conservan por corrida.')


def comparison_rows(bundles):
    rows=[]
    for b in bundles:
        i=b['identity']; p=b['profile_report']; c=p['counts']; d=p['distribution']
        total=c['selected_rows']; complete=c['completed']
        if total != complete+c['aborted']+c['censored']: raise ValueError('Denominador de completitud incoherente')
        if d.get('n_complete') != complete: raise ValueError('Muestra de duración incompatible')
        for key in ('mean_minutes','median_minutes','p95_minutes'):
            v=d.get(key)
            if (complete==0 and v is not None) or (v is not None and (not math.isfinite(v) or v<0)):
                raise ValueError('Duración sin muestra o no finita')
        rows.append(dict(run_id=i['run_id'],iteration=i['iteration'],N_configured=i['N_configured'],
            observed_selected_departures=total,completed=complete,aborted=c['aborted'],censored=c['censored'],
            completion_percent=100*complete/total if total else None,
            aborted_percent=100*c['aborted']/total if total else None,
            censored_percent=100*c['censored']/total if total else None,
            mean_minutes=d.get('mean_minutes'),median_minutes=d.get('median_minutes'),p95_minutes=d.get('p95_minutes'),
            duration_sample=d['n_complete'],excluded=c['aborted']+c['censored']))
    return finite(rows)


def generate_comparison(bundles, output):
    contract=compatibility(bundles); root=safe_output(output,bundles)
    key=hashlib.sha256(json.dumps([(b['identity']['run_id'],b['identity']['iteration']) for b in bundles]).encode()).hexdigest()[:12]
    pub=Publisher(root/'comparisons'/key,[b['identity'] for b in bundles],
                  [s for b in bundles for s in b['sources']],
                  {b['identity']['run_id']+':'+str(b['identity']['iteration']):b['source_versions'] for b in bundles})
    rows=comparison_rows(bundles); x=list(range(len(rows)))
    labels=[f'N={r["N_configured"]:,}\nit. {r["iteration"]}' for r in rows]
    if len(set(labels)) < len(labels): labels=[f'{label}\nserie {n+1}' for n,label in enumerate(labels)]
    width=max(9,2.3*len(rows))
    def values(key): return [math.nan if r[key] is None else r[key] for r in rows]
    def axes_style(ax,ylabel):
        ax.set_xticks(x,labels);ax.set_ylabel(ylabel);ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.2)
    meta=dict(objective='Comparación de escenarios e iteraciones completadas',
        units={'duration':'minutos','counts':'viajes/etapas observadas','percent':'% de salidas observadas seleccionadas'},
        filters=bundles[0]['profile_report']['filters'],
        denominators='Porcentaje: completed+aborted+censored de los seis perfiles; duración: sólo completed. N es población no pública configurada, no flujo.',
        calculation='Estadísticas publicadas por viaje; no promedio de medias ni extrapolación por N',
        observations=[r['duration_sample'] for r in rows],exclusions=[r['excluded'] for r in rows],compatibility=contract)
    fig,axs=plt.subplots(2,1,figsize=(width,8),layout='constrained')
    for shift,k,label,color in [(-.25,'mean_minutes','Media','#0072B2'),(0,'median_minutes','Mediana','#009E73'),(.25,'p95_minutes','P95','#D55E00')]:
        axs[0].bar([v+shift for v in x],values(k),width=.24,label=label,color=color)
    axes_style(axs[0],'Duración de etapas completas (min)');axs[0].legend(ncols=3)
    bottom=[0]*len(rows)
    for k,label,color in [('completed','Completas','#009E73'),('aborted','Abortadas','#D55E00'),('censored','Censuradas','#E69F00')]:
        vals=values(k);axs[1].bar(x,vals,bottom=bottom,label=label,color=color);bottom=[a+b for a,b in zip(bottom,vals)]
    axes_style(axs[1],'Viajes/etapas observadas');axs[1].legend(ncols=3)
    for j,r in enumerate(rows): axs[0].annotate(f'n={r["duration_sample"]:,}',(j,max([v for v in [r['mean_minutes'],r['median_minutes'],r['p95_minutes']] if v is not None] or [0])),xytext=(0,7),textcoords='offset points',ha='center',fontsize=9)
    fig.suptitle('Tiempos de viaje y conteos por escenario')
    pub.save(fig,'comparacion_escenarios_absolutos',rows,meta)
    fig,ax=plt.subplots(figsize=(width,5),layout='constrained'); bottom=[0]*len(rows)
    for k,label,color in [('completion_percent','Completas','#009E73'),('aborted_percent','Abortadas','#D55E00'),('censored_percent','Censuradas','#E69F00')]:
        vals=values(k);ax.bar(x,vals,bottom=bottom,label=label,color=color);bottom=[a+b for a,b in zip(bottom,vals)]
    axes_style(ax,'Porcentaje de salidas observadas (%)');ax.set_ylim(0,105);ax.legend(ncols=3,loc='upper center',bbox_to_anchor=(.5,-.12))
    for j,r in enumerate(rows): ax.text(j,101,f'den.={r["observed_selected_departures"]:,}',ha='center',fontsize=9)
    ax.set_title('Completitud normalizada por escenario')
    pub.save(fig,'comparacion_escenarios_normalizados',rows,meta)
    compare_spatial(bundles,pub)
    write_json(pub.directory/'compatibility.json',contract);pub.finish();return pub.directory


def compare_spatial(bundles,pub):
    """No zero placeholders for missing runs, spatial measures or coverage."""
    for key,ident_field,value_field,label,stem in [
        ('section_hour','section_id','vehicles_per_hour','Vehículos distintos / hora','comparacion_flujo_secciones'),
        ('occupancy_hour','intersection_id','mean_occupancy_vehicles','Ocupación media (vehículos)','comparacion_acumulacion')]:
        if not all(b.get('indicators',{}).get(key) for b in bundles):
            pub.pending.append(dict(indicator=stem,reason='Faltan tablas espaciales verificadas y equivalentes para todas las selecciones'))
            continue
        contracts=[b['indicators']['comparison_contract'] for b in bundles]
        if any(c!=contracts[0] for c in contracts[1:]):
            raise ValueError('Definiciones/cobertura de indicadores espaciales incompatibles')
        ids=sorted({r[ident_field] for r in bundles[0]['indicators'][key]})
        rows=[]
        for b in bundles:
            physical=b['identity']['counts'].get('all_vehicles_configured')
            for row in b['indicators'][key]:
                value=row[value_field]
                rows.append(dict(row,run_id=b['identity']['run_id'],iteration=b['identity']['iteration'],
                    N_configured=b['identity']['N_configured'],physical_vehicles_configured=physical,
                    per_1000_physical_configured=(1000*value/physical if value is not None and physical else None)))
        normalized=all(r['physical_vehicles_configured'] and r['physical_vehicles_configured']>0 for r in rows)
        fig,axs=plt.subplots(len(ids),2 if normalized else 1,figsize=(13 if normalized else 9,3.4*len(ids)+1.8),squeeze=False,layout='constrained')
        palette=plt.get_cmap('tab10')
        for j,ident in enumerate(ids):
            for k,b in enumerate(bundles):
                selected=[r for r in rows if r['run_id']==b['identity']['run_id'] and r['iteration']==b['identity']['iteration'] and r[ident_field]==ident]
                selected.sort(key=lambda r:r['hour'])
                legend=f'N={b["identity"]["N_configured"]:,} · it.{b["identity"]["iteration"]} · serie {k+1}'
                for col,field in enumerate([value_field]+(['per_1000_physical_configured'] if normalized else [])):
                    ax=axs[j,col];ax.plot([r['hour'] for r in selected],[r[field] if r[field] is not None else math.nan for r in selected],label=legend,color=palette(k%10))
                    ax.set_ylim(bottom=0);ax.set_xlim(0,max(24,b['identity']['horizon']['end_seconds']/3600))
                    ax.set_xticks(range(0,25,2),[f'{h:02d}:00' for h in range(0,25,2)])
                    ax.set_xlabel('Hora simulada');ax.set_ylabel(label+(' por 1000 físicos configurados' if col else ''))
                    ax.set_title(ident);ax.grid(alpha=.2);ax.legend(fontsize=8)
        fig.suptitle('Flujo en secciones equivalentes' if key=='section_hour' else 'Ocupación en intersecciones equivalentes')
        pub.save(fig,stem,rows,dict(objective='Comparación de escenarios: flujo y acumulación',
            units=label,filters=contracts[0],denominators='Serie normalizada: total físico configurado del manifiesto (incluye flota pública); no es fracción de viajes ni crecimiento proporcional de flujo.',
            calculation='Indicador absoluto de cada hora; normalizado = 1000 × indicador / flota física configurada, sólo con denominador válido',
            observations=len(rows),exclusions=sum(r[value_field] is None for r in rows)))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_subparsers(dest='mode',required=True)
    single=modes.add_parser('individual');single.add_argument('--run-dir',required=True,type=Path)
    single.add_argument('--iteration',required=True,type=int);single.add_argument('--output',required=True,type=Path)
    single.add_argument('--diagnostic',action='store_true')
    single.add_argument('--indicators',type=Path,action='append')
    single.add_argument('--temporal-resolution',choices=('original','hourly'),default='original')
    comp=modes.add_parser('compare');comp.add_argument('--run',nargs=2,action='append',required=True,metavar=('RUN_DIR','ITERATION'))
    comp.add_argument('--output',required=True,type=Path)
    comp.add_argument('--indicators',type=Path,action='append')
    args=parser.parse_args(argv);style()
    try:
        if args.mode=='individual':
            bundle=load_bundle(args.run_dir,args.iteration,args.diagnostic)
            bundle['temporal_resolution']=args.temporal_resolution
            attach_indicators([bundle],args.indicators)
            destination=generate_individual(bundle,args.output)
        else:
            bundles=[load_bundle(p,int(it)) for p,it in args.run]
            attach_indicators(bundles,args.indicators)
            destination=generate_comparison(bundles,args.output)
        print(json.dumps(dict(status='generated',destination=str(destination),version=VERSION),ensure_ascii=False));return 0
    except (ValueError,KeyError,OSError,TypeError) as exc:
        print('RECHAZADO: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__': raise SystemExit(main())
