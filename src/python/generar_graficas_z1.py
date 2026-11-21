import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Exportacion sin ventana ni dependencia de Tcl/Tk.
import matplotlib.pyplot as plt
import argparse
import json
import math
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def iteration_metrics(run_dir):
    """MATSim 15 exports scorestats at run root and legdurations per iteration."""
    run_dir = Path(run_dir)
    scores = {}
    score_file = run_dir/'scorestats.txt'
    if score_file.exists():
        table = pd.read_csv(score_file, sep='\t')
        scores = dict(zip(table['ITERATION'], table['avg. EXECUTED']))
    folders = sorted((p for p in (run_dir/'ITERS').glob('it.*')
                      if p.is_dir() and re.fullmatch(r'it\.\d+', p.name)),
                     key=lambda p: int(p.name[3:]))
    if not folders:
        raise ValueError(f'No hay directorios ITERS/it.* en {run_dir}')
    records = []
    for folder in folders:
        iteration = int(folder.name[3:])
        mean = math.nan
        source = None
        # Exact all-mode mean exported by MATSim; never estimate from histogram bins.
        for candidate in (folder/'traveltimes.txt', folder/f'{iteration}.traveltimes.txt',
                          folder/f'{iteration}.legdurations.txt'):
            if not candidate.exists():
                continue
            text = candidate.read_text(encoding='utf-8-sig')
            match = re.search(r'average (?:leg|trip) duration:\s*([\d.eE+-]+)\s*seconds', text)
            if match:
                mean = float(match[1])/60
                source = candidate
                break
            if candidate.name.endswith('traveltimes.txt'):
                table = pd.read_csv(candidate, sep='\t')
                # Units must be explicit: never guess seconds vs minutes.
                if 'mean_travel_time_seconds' in table:
                    if 'iteration' in table:
                        table = table[table.iteration == iteration]
                    if len(table) == 1:
                        mean = float(table.iloc[0]['mean_travel_time_seconds'])/60
                        source = candidate
                        break
        if source is None:
            candidate = folder/f'{iteration}.legs.csv.gz'
            if candidate.exists():
                total = 0.; count = 0
                for chunk in pd.read_csv(candidate, sep=';', usecols=['trav_time'], chunksize=50000):
                    durations = pd.to_timedelta(chunk.trav_time, errors='raise').dt.total_seconds().dropna()
                    total += durations.sum(); count += len(durations)
                mean = total/count/60 if count else math.nan
                source = candidate
        if math.isfinite(mean) and mean < 0:
            raise ValueError(f'Duracion negativa: {source}')
        records.append(dict(Iteration=iteration, Mean_Travel_Time_Minutes=mean,
                            Executed_Score=scores.get(iteration, math.nan),
                            Source=str(source.relative_to(run_dir)) if source else '',
                            Status='ok' if math.isfinite(mean) else 'sin datos'))
    return pd.DataFrame(records)


def generar_historial(run_dir, iteration=None, provenance=None):
    run_dir = Path(run_dir).resolve()
    frame = iteration_metrics(run_dir)
    if iteration is not None:
        frame = frame[frame.Iteration <= iteration].reset_index(drop=True)
    if not frame.Mean_Travel_Time_Minutes.notna().any():
        raise ValueError('No se encontraron duraciones medias reconocibles; no se convierten scores a minutos.')
    output = run_dir/'graficas_aprendizaje'
    if iteration is not None:
        output = output/f'hasta-{iteration}'
    output.mkdir(parents=True, exist_ok=True)
    frame.drop(columns='Executed_Score').to_csv(output/'metricas_iteraciones.csv', index=False)
    frame[['Iteration','Executed_Score']].to_csv(output/'puntajes_iteraciones.csv',index=False)
    for index, row in frame.iterrows():
        history = frame.iloc[:index+1]
        fig, ax = plt.subplots(figsize=(10,6))
        ax.plot(history.Iteration, history.Mean_Travel_Time_Minutes, '-o', color='#087eaa')
        ax.set(xlabel='Iteracion', ylabel='Duracion media por etapa de viaje (minutos)',
               title=f'Zona 1: aprendizaje hasta la iteracion {row.Iteration}')
        ax.grid(alpha=.3)
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        if row.Status != 'ok':
            ax.text(.5,.95,'Sin dato de duracion en esta iteracion',transform=ax.transAxes,ha='center')
        fig.text(.5,.01,'Promedio de etapas registradas; no prueba por si solo una mejora ni incluye viajes abortados.',
                 ha='center',fontsize=8)
        fig.tight_layout(rect=(0,.03,1,1))
        fig.savefig(output/f'iteracion_{int(row.Iteration):03d}.png', dpi=200)
        plt.close(fig)
    report = dict(iterations=len(frame), missing_iterations=frame.loc[frame.Status!='ok','Iteration'].tolist(),
                  metric='Mean leg duration in minutes; all recorded modes',
                  n_complete=None,n_excluded=None,
                  completeness='Unknown from legacy aggregates; use compact trip distributions for terminal states and counts.',
                  score_source='scorestats.txt' if (run_dir/'scorestats.txt').exists() else None)
    if provenance:
        report.update(provenance)
    (output/'reporte.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'{len(frame)} graficas: {output}')
    return frame


def generar_graficas(selection, mode='car', table=None):
    from simz1_trip_table import export_table
    from simz1_trip_distributions import distributions
    table = table or export_table(selection)[0]
    _,_,summaries,report = distributions(table,mode)
    hours = sorted((row for row in summaries if row['view']=='hour' and row['n_complete']),key=lambda row:row['hour'])
    if not hours:
        raise ValueError('No hay viajes completados para graficar')
    destination = selection['directory']/'analysis'/f"it.{selection['iteration']}"/'grafica_tiempos_zona1.png'
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar([str(row['hour']) for row in hours],[row['mean_seconds']/60 for row in hours],color='#087eaa')
    ax.set(xlabel='Hora absoluta de departure', ylabel='Duracion media de etapa completada (minutos)',
           title=f"SimZ1 {selection['manifest']['run_id']} / iteracion {selection['iteration']} / modo={mode}\n"
                 f"N completos={report['n_complete']}; excluidos={report['n_excluded']}")
    fig.tight_layout()
    fig.savefig(destination, dpi=200)
    plt.close(fig)
    print(f'Grafica: {destination}')


def main():
    from simz1_run import select_run
    parser = argparse.ArgumentParser(description='Graficas de una corrida SimZ1 validada')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--iteration', type=int, help='Ultima iteracion del historial / iteracion del grafico horario')
    parser.add_argument('--hourly', action='store_true', help='Grafica adicional de medias horarias del modo seleccionado')
    parser.add_argument('--mode',default='car',help='Modo exacto de departure; all mezcla modos de forma explicita')
    parser.add_argument('--person',help='Persona para seguimiento entre iteraciones')
    parser.add_argument('--trip-index',type=int,help='Ordinal de departure dentro de persona/iteracion, contando todos los modos')
    parser.add_argument('--learning',action='store_true',help='Conserva adicionalmente el historial agregado anterior, de todos los modos')
    parser.add_argument('--scores',action='store_true',help='Exporta puntajes a un producto separado, sin convertirlos en duraciones')
    parser.add_argument('--analysis-dir', type=Path,
                        help='Raiz de analisis alternativa; escribe it.N/ sin modificar la corrida fuente')
    parser.add_argument('--profiles-only', action='store_true', help='Solo entregable principal por perfiles (incluye histograma real)')
    parser.add_argument('--all-iterations', action='store_true',
                        help='Genera o reutiliza el entregable principal de todas las iteraciones completadas y validadas')
    parser.add_argument('--min-sample', type=int, default=30, help='Marca muestras con menos de N viajes completos; no es prueba de significancia')
    args = parser.parse_args()
    try:
        if (args.person is None)!=(args.trip_index is None):raise ValueError('Use --person y --trip-index juntos')
        if args.trip_index is not None and args.trip_index<1:raise ValueError('--trip-index debe ser positivo')
        if args.min_sample < 1:raise ValueError('--min-sample debe ser positivo')
        if args.analysis_dir and (args.learning or args.person is not None or args.hourly):
            raise ValueError('--analysis-dir no admite --learning, --person ni --hourly: esos productos usan rutas de la corrida')
        if args.profiles_only and (args.learning or args.person is not None or args.hourly or args.scores):
            raise ValueError('--profiles-only no se combina con productos opcionales anteriores')
        if args.all_iterations:
            if args.iteration is not None or args.learning or args.person is not None or args.hourly or args.scores:
                raise ValueError('--all-iterations no se combina con --iteration ni productos opcionales anteriores')
            from simz1_analysis import analyze_run
            result = analyze_run(args.run_dir, all_iterations=True, analysis_dir=args.analysis_dir, min_sample=args.min_sample)
            for item in result['iterations']:
                print(f"Iteracion {item['iteration']}: {item['status']} | {item['directory']} | reutilizado={item.get('reused', False)}")
                if item.get('error'):print(item['error'])
            if result['status'] != 'completed':
                parser.exit(2, 'analysis_failed: MATSim no se modifica; reintente el mismo comando.\n')
            return
        selection = select_run(args.run_dir, args.iteration, require_events=False)
        from simz1_analysis import analyze_selection
        result = analyze_selection(selection, analysis_dir=args.analysis_dir, min_sample=args.min_sample)
        if result['status'] != 'completed':
            parser.exit(2, f"analysis_failed: {result.get('error', result['status'])}; MATSim no se modifica.\n")
        destination = Path(result['directory'])
        profile_destination = destination/'graficas_perfiles'
        table=destination/'trips.csv.gz'
        report=json.loads(table.with_suffix('.provenance.json').read_text(encoding='utf-8'))
        from simz1_trip_distributions import plot_distributions,follow_person
        profiles=json.loads((profile_destination/'resumen_perfiles.json').read_text(encoding='utf-8'))
        print(f"Entregable principal: {profile_destination} | N completos={profiles['distribution']['n_complete']} | reutilizado={result.get('reused', False)}")
        if args.profiles_only:
            return
        legacy_files = ('duration_distribution.png','profile_hour_distribution.png','percentiles_profile_hour.csv','distribution_summary.json')
        if not any((destination/name).exists() for name in legacy_files):
            summary=plot_distributions(table,destination,f"{selection['manifest']['run_id']} / iteracion {selection['iteration']}",args.mode)
        else:
            summary=None
            print('Distribuciones anteriores conservadas sin sobrescribir.')
        if args.person is not None:
            if any((destination/name).exists() for name in ('individual_evolution.csv','individual_evolution.png','individual_summary.json')):
                print('Seguimiento individual anterior conservado sin sobrescribir.')
            else:
                follow_person(selection,args.person,args.trip_index,destination,args.mode,{selection['iteration']:table})
        else:print('Seguimiento individual disponible con --person ID --trip-index N; no se generan PNG por persona.')
        if args.hourly:
            if (destination/'grafica_tiempos_zona1.png').exists():
                print('Grafica horaria anterior conservada sin sobrescribir.')
            else:
                generar_graficas(selection,args.mode,table)
        if args.learning:
            learning=selection['directory']/'output/graficas_aprendizaje'/f"hasta-{selection['iteration']}"
            if learning.exists() and any(learning.iterdir()):
                print('Historial anterior conservado sin sobrescribir.')
            else:
                generar_historial(selection['directory']/'output', selection['iteration'],
                                  dict(run_id=selection['manifest']['run_id'], selected_iteration=selection['iteration']))
        if args.scores:
            source=selection['directory']/'output/scorestats.txt'
            if not source.is_file():raise ValueError('No hay scorestats; no se sustituye con duracion')
            if not (destination/'scores_only.csv').exists():
                scores=pd.read_csv(source,sep='\t');scores.to_csv(destination/'scores_only.csv',index=False)
        print(f"Distribuciones: {destination} | fuente={report['source_kind']} | modo={args.mode}")
        if summary:
            print(f"N completos={summary['n_complete']}; excluidos={summary['n_excluded']}; completitud={summary['completion_rate']}")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'No se pudo graficar: {exc}\n')


if __name__ == '__main__':
    main()
