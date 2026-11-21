"""Bounded-memory, unsampled SimZ1 replay export with complete journeys on disk.

The event stream is read once. Intervals are immediately spooled to SQLite;
after trip metadata is final, kinematics is evaluated one journey at a time.
Each HTML contains only intervals intersecting its explicit time window. A
read-only localhost server supplies the complete selected journey on demand.
"""
from bisect import bisect_left
from collections import Counter
from contextlib import closing
import hashlib
import html
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import zlib


def packed(value):
    return zlib.compress(json.dumps(value,separators=(',',':'),allow_nan=False).encode('utf-8'),1)


def unpacked(value):
    return json.loads(zlib.decompress(value))


def journey_key(segment):
    trip=segment.get('Trip') or {}
    identity=[segment.get('Agent_ID'),trip.get('Trip_ID'),trip.get('Departure')]
    if identity[1] is None and identity[2] is None:
        identity.append(segment.get('vehicle'))
    return hashlib.sha256(json.dumps(identity,separators=(',',':')).encode('utf-8')).hexdigest()


def windows(start,end,seconds):
    if not all(math.isfinite(v) for v in (start,end,seconds)) or not 0<=start<end or seconds<=0:
        raise ValueError('Ventanas requieren 0 <= inicio < fin y duracion positiva finita')
    count=math.ceil((end-start)/seconds)
    return [dict(index=i,start_seconds=start+i*seconds,end_seconds=min(end,start+(i+1)*seconds),
                 url=f'{i:04d}.html') for i in range(count)]


class SqliteTrajectorySink:
    """List-compatible append/count, without retaining segment histories in RAM."""
    def __init__(self,path,blocks,*,storage_guard=None,temp_dir=None,max_database_bytes=None):
        self.path=Path(path)
        if self.path.exists():
            raise ValueError(f'El archivo de replay ya existe; use una carpeta nueva: {self.path}')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.connection=sqlite3.connect(self.path)
        self.storage_guard=storage_guard
        if temp_dir is not None:
            temporary = str(Path(temp_dir).resolve(strict=True))
            # SQLite on Windows does not honor SQLITE_TMPDIR. This process is
            # an offline exporter; configure its actual SQLite temp directory.
            self.connection.execute("PRAGMA temp_store_directory='" + temporary.replace("'", "''") + "'")
            configured = self.connection.execute('PRAGMA temp_store_directory').fetchone()
            if not configured or Path(configured[0]).resolve() != Path(temporary):
                self.connection.close()
                raise ValueError('SQLite no permite configurar scratch; exportacion detenida')
        self.connection.executescript('''
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=FILE;
            PRAGMA cache_size=-32768;
            CREATE TABLE segments(id INTEGER PRIMARY KEY, journey TEXT NOT NULL,
                vehicle TEXT, start REAL NOT NULL, end REAL NOT NULL, payload BLOB NOT NULL);
            CREATE TABLE segment_blocks(block INTEGER NOT NULL, segment INTEGER NOT NULL);
            CREATE TABLE journeys(key TEXT PRIMARY KEY, metadata TEXT);
            CREATE TABLE lane_events(seq INTEGER PRIMARY KEY, vehicle TEXT, time REAL, payload BLOB);
            CREATE TABLE export_identity(key TEXT PRIMARY KEY, value TEXT);
        ''')
        if max_database_bytes is not None:
            page_size=self.connection.execute('PRAGMA page_size').fetchone()[0]
            self.connection.execute(f'PRAGMA max_page_count={max(1,int(max_database_bytes)//page_size)}')
        self.blocks=blocks
        self._trips={}
        self.count=0
        self.lane_count=0
        self.block_occurrences=0
        self.outside_window=0
        self.finalized=False
        self.started=time.perf_counter()
        self.timings={}

    def __len__(self):
        return self.count

    def register_trip(self,trip,person):
        # Preserve aborts/censored journeys even when no link boundary closes.
        # These metadata records do not create a drawable position or segment.
        self._trips[journey_key(dict(Trip=trip,Agent_ID=person))]=trip

    def set_identity(self,run_id,iteration,manifest_hash):
        self.connection.executemany('INSERT INTO export_identity VALUES(?,?)',
            [('run_id',run_id),('iteration',str(iteration)),('run_manifest_sha256',manifest_hash)])
        self.connection.commit()

    def append(self,segment):
        if self.finalized:
            raise ValueError('El spool ya esta finalizado')
        key=journey_key(segment)
        trip=segment.get('Trip')
        if key not in self._trips:
            self._trips[key]=trip  # The extractor continues updating this shared dictionary.
        segment=dict(segment,Replay_Journey_Key=key)
        segment.pop('Trip',None)
        start,end=segment['timestamps']
        self.count+=1
        self.connection.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',
            (self.count,key,segment['vehicle'],start,end,packed(segment)))
        # Exact overlap: [start,end) belongs to each intersected block, never
        # both sides of an exclusive endpoint. Zero-length evidence is retained.
        if self.blocks and start < self.blocks[-1]['end_seconds']:
            origin=self.blocks[0]['start_seconds']
            duration=self.blocks[0]['end_seconds']-origin
            first=max(0,math.floor((start-origin)/duration))
            last=min(len(self.blocks)-1,math.floor(((math.nextafter(end,-math.inf) if end>start else end)-origin)/duration))
            if first<=last:
                self.connection.executemany('INSERT INTO segment_blocks VALUES(?,?)',
                    ((index,self.count) for index in range(first,last+1)))
                self.block_occurrences+=last-first+1
            else:
                self.outside_window+=1
        elif self.blocks:
            # A final partial bucket still has an exclusive endpoint. Keep the
            # native record in segments, without assigning it beyond the index.
            self.outside_window+=1
        if self.count%10000==0:
            if self.storage_guard:self.storage_guard()
            self.connection.commit()
        if self.count%100000==0:
            print(f'Spool: {self.count:,} tramos; {len(self._trips):,} viajes registrados; sin historiales en RAM',flush=True)

    def append_lane(self,record):
        self.lane_count+=1
        self.connection.execute('INSERT INTO lane_events VALUES(?,?,?,?)',
            (self.lane_count,record['vehicle'],record['time'],packed(record)))
        if self.lane_count%20000==0:
            if self.storage_guard:self.storage_guard()
            self.connection.commit()

    def finalize(self,*,settings,observation_end):
        from simz1_visual_motion import apply_visual_motion,normalize_settings
        if self.finalized:
            raise ValueError('El spool ya esta finalizado')
        started=time.perf_counter()
        self.timings['event_spool']=started-self.started
        self.connection.commit()
        if self.storage_guard:self.storage_guard(indexes=True)
        self.connection.executescript('''
            CREATE INDEX segments_journey ON segments(journey,id);
            CREATE INDEX segments_block ON segment_blocks(block,segment);
            CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);
            CREATE INDEX lanes_time ON lane_events(time,seq);
        ''')
        motion_started=time.perf_counter()
        self.timings['sqlite_indexes']=motion_started-started
        counts=Counter()
        all_vehicles,representable,available_plans=set(),set(),set()
        end_active={}
        censored_without_closed=censored_without_active=censored_journeys=0
        for number,(key,trip) in enumerate(self._trips.items(),1):
            if trip is not None and trip.get('Observation_End') is None:
                trip['Observation_End']=observation_end
            self.connection.execute('INSERT INTO journeys VALUES(?,?)',
                (key,json.dumps(trip,separators=(',',':'),allow_nan=False)))
            rows=self.connection.execute('SELECT id,payload FROM segments WHERE journey=? ORDER BY start,end,id',(key,)).fetchall()
            records=[]
            for _,raw in rows:
                record=unpacked(raw);record['Trip']=trip;records.append(record)
            summary=apply_visual_motion(records,settings=settings)
            counts.update(summary['counts'])
            if trip and trip.get('Status')=='censored':
                censored_journeys+=1
                censored_without_closed+=not records
                censored_without_active+=not any(observation_end is not None and
                    record['timestamps'][0]<=observation_end<record['timestamps'][1] for record in records)
            maxima={}
            for record in records:
                vehicle=record['vehicle'];speed=record.get('Speed_kmh')
                all_vehicles.add(vehicle)
                if record['Motion_Plan']['status']!='unavailable':
                    available_plans.add(vehicle)
                    if record['timestamps'][1]>record['timestamps'][0]:representable.add(vehicle)
                if observation_end is not None and record['timestamps'][0]<=observation_end<record['timestamps'][1]:
                    previous=end_active.get(vehicle)
                    if previous is None or previous[0]<=record['timestamps'][0]:
                        end_active[vehicle]=(record['timestamps'][0],record.get('Agent_ID'),record['Motion_Plan']['status']!='unavailable')
                if speed is not None and math.isfinite(speed):
                    maxima[vehicle]=max(maxima.get(vehicle,-math.inf),speed)
                record['Max_Speed_kmh']=maxima.get(vehicle)
                record.pop('Trip',None)
            self.connection.executemany('UPDATE segments SET payload=? WHERE id=?',
                ((packed(record),row[0]) for record,row in zip(records,rows)))
            if number%1000==0:
                if self.storage_guard:self.storage_guard()
                self.connection.commit()
                print(f'Cinematica en disco: {number}/{len(self._trips)} viajes',flush=True)
        self.connection.commit()
        self._trips.clear()
        self.finalized=True
        self.visual_vehicle_counts=dict(reconstructed=len(all_vehicles),with_representable_interval=len(representable),
            without_representable_interval=len(all_vehicles-representable),
            only_unavailable_motion_plans=len(all_vehicles-available_plans))
        self.observation_end_probe=dict(time_seconds=observation_end,
            vehicles_with_closed_interval_active=len(end_active),
            representable_vehicles=sum(value[2] for value in end_active.values()),
            visible_agents=len({value[1] for value in end_active.values() if value[2] and value[1] is not None}),
            unavailable_interval_vehicles=sum(not value[2] for value in end_active.values()),
            censored_journeys=censored_journeys,censored_without_any_closed_interval=censored_without_closed,
            censored_without_closed_interval_at_observation_end=censored_without_active,
            source='Exact native interval membership and exported Motion_Plan availability; no extrapolation; not browser FPS')
        self.timings['complete_journey_motion']=time.perf_counter()-motion_started
        normalized=normalize_settings(settings)
        return dict(version=1,enabled=normalized['enabled'],segments=self.count,counts=dict(counts),settings=normalized)

    def block_records(self,index):
        if not self.finalized:
            raise ValueError('Las fases y los viajes aun no estan finalizados')
        records=[]
        metadata={}
        # Sorting BLOBs and trip metadata in SQLite spilled a large transient
        # B-tree to the system drive. These records already live in Python;
        # sort references here and never duplicate the payload in a disk sort.
        for ident,start,end,key,raw,trip in self.connection.execute('''SELECT s.id,s.start,s.end,s.journey,s.payload,j.metadata
                FROM segment_blocks b JOIN segments s ON s.id=b.segment
                JOIN journeys j ON j.key=s.journey WHERE b.block=?''',(index,)):
            if key not in metadata:
                metadata[key]=json.loads(trip)
            record=unpacked(raw);record['Trip']=metadata[key]
            records.append((start,end,ident,record))
        records.sort(key=lambda item:item[:3])
        return [item[3] for item in records]

    def block_lanes(self,start,end,vehicles):
        records=[]
        for vehicle in vehicles:
            row=self.connection.execute('SELECT seq,payload FROM lane_events WHERE vehicle=? AND time<? ORDER BY time DESC,seq DESC LIMIT 1',
                (vehicle,start)).fetchone()
            if row:
                records.append((row[0],unpacked(row[1])))
        for seq,raw in self.connection.execute('SELECT seq,payload FROM lane_events WHERE time>=? AND time<? ORDER BY time,seq',(start,end)):
            record=unpacked(raw)
            if record['vehicle'] in vehicles:
                records.append((seq,record))
        records.sort(key=lambda pair:(pair[1]['time'],pair[0]))
        return [record for _,record in records]

    def close(self):
        self.connection.close()


class LaneSink:
    def __init__(self,store):
        self.store=store

    def append(self,record):
        self.store.append_lane(record)


class ReplayPayload:
    def __init__(self,payload,groups=None):
        self.data=payload
        self.groups=groups

    def payload(self,*args):
        return self.data


def signal_window(replay,start,end):
    """Retain the latest native predecessor plus all transitions in [start,end)."""
    series=[]
    for group in replay.groups:
        states=replay.series[group['system_id'],group['group_id']]
        begin=bisect_left(states,start,key=lambda state:state[0])
        stop=bisect_left(states,end,key=lambda state:state[0])
        series.append(dict(**group,states=states[max(0,begin-1):stop]))
    return ReplayPayload(dict(**replay.summary(),series=series,
        retained_state_events=sum(len(group['states']) for group in series),window=[start,end],
        predecessor_policy='last native observation before the block, no synthetic phase'),replay.groups)


def annotate_observation_times(report, observed_event_end_seconds, operational_report=None):
    """Keep the exact native snapshot clock apart from whole-stream trip totals."""
    report['operational_counts_observation_end_seconds']=observed_event_end_seconds
    probe=report['observation_end_probe']
    probe.pop('native_pending_trips_at_horizon',None)
    probe['native_pending_trips_at_stream_end']=report['operational_counts'].get('pending_legs_at_horizon')
    probe['native_pending_reference_time_seconds']=observed_event_end_seconds
    if operational_report is not None:
        if (operational_report['run_id']!=report['run_id'] or
                operational_report['iteration']!=report['iteration'] or
                operational_report['manifest_sha256']!=report['run_manifest_sha256']):
            raise ValueError('El informe operativo no corresponde al replay validado')
        pending=operational_report['pending']
        if pending['active_snapshot_seconds']==probe['time_seconds']:
            probe['native_active_vehicles_at_probe_time']=pending['active_vehicles_snapshot']
            probe['native_active_snapshot_source']=operational_report['source_records']['progress_log']
    return report


def index_html(report):
    escape=lambda value:html.escape(str(value),quote=True)
    preferred=next((block for block in report['blocks'] if block['start_seconds']==25200),report['blocks'][0])
    launch=f'<a href="blocks/{escape(preferred["url"])}"><strong>Abrir mapa WebGL · {clock(preferred["start_seconds"])}</strong></a>'
    rows=''.join(f'<tr><td><a href="blocks/{escape(block["url"])}">{block["index"]+1}</a></td>'
        f'<td>{clock(block["start_seconds"])}–{clock(block["end_seconds"])}</td>'
        f'<td>{block["segments"]:,}</td><td>{block["vehicles"]:,}</td><td>{block["html_bytes"]/1024**2:.1f} MiB</td></tr>'
        for block in report['blocks'])
    operational=' · '.join(escape(label)+': '+f'{report["operational_counts"][key]:,}'
        for key,label in [('completed_legs','Llegadas completadas'),('pending_legs_at_horizon','Pendientes al cierre de eventos'),
                          ('aborted_before_horizon','Abortados antes del horizonte'),('unstarted_legs','Sin iniciar')]
        if key in report.get('operational_counts',{}))
    probe=report['observation_end_probe']
    timing_note=(' Cierre del archivo: '+clock(report['operational_counts_observation_end_seconds'])+'.'
        if report.get('operational_counts_observation_end_seconds') is not None else '')
    if probe.get('native_active_vehicles_at_probe_time') is not None:
        timing_note+=f' A las {clock(probe["time_seconds"])}, QSim registró {probe["native_active_vehicles_at_probe_time"]:,} vehículos dentro de la red.'
    return f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SimZ1 — bloques de replay</title><style>body{{background:#101820;color:#fff;font:15px/1.5 system-ui;margin:24px;max-width:1100px}}a{{color:#a8d5ff}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:7px;border-bottom:1px solid #ffffff24}}code{{overflow-wrap:anywhere}}</style>
<h1>SimZ1 · replay por bloques</h1><p>Corrida <code>{escape(report['run_id'])}</code> · Iteración {report['iteration']}.</p>
<p>{launch}</p>
<p>{report['planned_persons']:,} personas y {report['planned_trips']:,} viajes planificados.
{report['counts']['reconstructed_vehicles']:,} vehículos reconstruidos; {report['counts']['segments']:,} tramos.
<strong>Sin muestreo: 100 % de los eventos seleccionados.</strong></p>
<p>{operational}. Conteos del archivo completo de eventos; el paso terminal de QSim puede quedar después del horizonte configurado.{timing_note}</p>
<p>Abra un bloque para consultar su hora absoluta, vehículos activos, señales e incidentes nativos.
Los viajes que cruzan un borde conservan sus tiempos y fases originales. El recorrido completo del viaje seleccionado se carga bajo demanda desde el servidor local.</p>
<p>{report['visual_vehicle_counts']['with_representable_interval']:,} vehículos tienen al menos un intervalo visual representable;
{report['visual_vehicle_counts']['without_representable_interval']:,} vehículos reconstruidos no tienen ninguno.
Los intervalos incompatibles con sus límites se conservan como huecos explícitos, sin posición inventada. Activos visibles cuenta marcadores dibujables, no la población activa de QSim.</p>
<p>En t={report['observation_end_probe']['time_seconds']:g} s, los intervalos cerrados permiten representar
{report['observation_end_probe']['visible_agents']:,} agentes. Los viajes pendientes nativos al cierre de eventos se informan arriba;
un enlace abierto sin salida observada no proporciona una posición dibujable en ese instante.</p>
<p>{len(report['blocks'])} bloques de hasta {report['window_seconds']:g} segundos; cambiar de bloque libera la memoria del anterior.
El número de vehículos de un bloque no es el total de personas planificadas ni el número activo en un instante.</p>
<p>Un tramo que cruza el borde aparece en ambos bloques con los mismos tiempos y fases;
el total de tramos de la corrida cuenta cada intervalo una sola vez.</p>
<table><thead><tr><th>Bloque</th><th>Hora absoluta</th><th>Tramos cargados</th><th>Vehículos</th><th>Tamaño HTML</th></tr></thead><tbody>{rows}</tbody></table>
<p><a href="export-manifest.json">Procedencia y mediciones de exportación</a>. La interpolación visual no modifica QSim.</p></html>'''


def clock(seconds):
    seconds=int(seconds)
    return f'{seconds//3600:02d}:{seconds%3600//60:02d}:{seconds%60:02d}'


def peak_working_set():
    """Native process peak, without slowing millions of records with tracemalloc."""
    if os.name!='nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    info=Counters();info.cb=ctypes.sizeof(info)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb):
        raise ctypes.WinError()
    return info.PeakWorkingSetSize


def export_paged_selected(selection,output=None,replay_start=None,replay_end=None,*,
                          trajectories_only=False,visual_settings=None,window_seconds=900):
    import visualizador_z1 as viewer
    from simz1_lane_replay import LaneEventReplay
    from simz1_motion import load_selected
    from simz1_run import atomic_json,sha256
    from simz1_signal_replay import SignalReplay,selected_groups
    if viewer.SAMPLE_RATE!=1:
        raise ValueError('El export paginado no admite muestreo implicito; SAMPLE_RATE debe ser 1')
    manifest=selection['manifest'];result=manifest['results'][str(selection['iteration'])]
    chosen=dict(manifest.get('replay_window',manifest['time_horizon']))
    chosen['end_seconds']=max(chosen['end_seconds'],result.get('observed_event_end_seconds',0))
    if replay_start is not None:chosen['start_seconds']=replay_start
    if replay_end is not None:chosen['end_seconds']=replay_end
    blocks=windows(chosen['start_seconds'],chosen['end_seconds'],window_seconds)
    destination=Path(output) if output else Path(selection['directory'])/'webgl'/'index.html'
    if destination.name!='index.html':
        raise ValueError('El export paginado requiere --output <carpeta>/index.html')
    folder=destination.parent;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'export-manifest.json').exists():
        raise ValueError('La carpeta ya contiene un export; use otra carpeta para conservar su identidad')
    if (folder/'replay.sqlite').exists():
        raise ValueError('Export interrumpido con SQLite existente: use python/simz1_recover_paged.py '
                         '--run-dir <corrida> --source <carpeta>; no vuelva a extraer trayectorias')
    started=time.perf_counter()
    print(f'Export paginado PID={os.getpid()} | {manifest["run_id"]} | iteracion {selection["iteration"]} | '
          f'{len(blocks)} bloques de {window_seconds:g}s | sin muestreo',flush=True)
    manifest_path=Path(selection['directory'])/'run-manifest.json'
    manifest_hash=sha256(manifest_path)
    motion=load_selected(selection,visual_settings=visual_settings)
    viewer.NETWORK_FILE,viewer.EVENTS_FILE=selection['network'],selection['events']
    links,signals=viewer.extraer_red()
    incidents=[];stats={}
    native_signals=SignalReplay(selected_groups(selection,links))
    metadata_done=time.perf_counter()
    with closing(SqliteTrajectorySink(folder/'replay.sqlite',blocks)) as store:
        store.set_identity(manifest['run_id'],selection['iteration'],manifest_hash)
        lanes=None if trajectories_only else LaneEventReplay(links,event_sink=LaneSink(store))
        viewer.extraer_trayectorias(links,incidents,lanes,None if trajectories_only else native_signals,
            motion=motion,stats=stats,horizon=manifest['time_horizon']['end_seconds'],segment_sink=store)
        extraction_done=time.perf_counter()
        selected=dict(selection,trajectory_stats=stats,motion_sources=motion.sources,trajectories_only=trajectories_only)
        for block in blocks:
            block_started=time.perf_counter()
            records=store.block_records(block['index'])
            vehicles={record['vehicle'] for record in records}
            start,end=block['start_seconds'],block['end_seconds']
            lane_payload=None
            if lanes is not None:
                events=store.block_lanes(start,end,vehicles)
                lane_payload=ReplayPayload(dict(lanes.payload(),events=events,retained_events=len(events),window=[start,end]))
            signal_payload=signal_window(native_signals,start,end)
            pagination=dict(block_index=block['index'],block_count=len(blocks),window_seconds=window_seconds,
                index_url='../index.html',blocks=[{k:b[k] for k in ('index','start_seconds','end_seconds','url')} for b in blocks],
                journey_endpoint='../api/journey',sample_rate=1.0,total_reconstructed_vehicles=stats['reconstructed_vehicles'],
                total_segments=stats['segments'],loaded_segments=len(records),
                visual_vehicle_counts=store.visual_vehicle_counts,
                full_journey_policy='read-only localhost lookup on selection; complete native trip and motion phases')
            block_path=folder/'blocks'/block['url']
            viewer.generar_html_animado(records,links,signals,
                [incident for incident in incidents if incident['start']<end and (incident['end'] is None or incident['end']>start)],
                selection=selected,output=block_path,lane_replay=lane_payload,replay_window=dict(start_seconds=start,end_seconds=end),
                signal_replay=signal_payload,visual_settings=motion.visual_settings,
                replay_extra={'pagination':pagination,'operational_counts':result['counts']})
            block.update(segments=len(records),vehicles=len(vehicles),html_bytes=block_path.stat().st_size,
                         export_seconds=time.perf_counter()-block_started)
            print(f'Bloque {block["index"]+1}/{len(blocks)}: {len(records)} tramos, {block["html_bytes"]/1024**2:.1f} MiB',flush=True)
        store.connection.commit()
        spool_timings=dict(store.timings)
        block_occurrences=store.block_occurrences
        outside_window=store.outside_window
        visual_vehicle_counts=dict(store.visual_vehicle_counts)
        end_probe=dict(store.observation_end_probe,
            native_pending_trips_at_horizon=result['counts'].get('pending_legs_at_horizon'),
            pending_link_intervals_after_event_stream=stats.get('pending_link_intervals',0),
            unclosed_intervals_removed_at_abort=stats.get('unclosed_intervals_at_abort',0),
            interpretation='Native pending trips and visible markers are different quantities. Missing exit boundaries are not extrapolated; unavailable plans retain explicit gaps.')
    if sha256(manifest_path)!=manifest_hash:
        raise ValueError('El manifiesto de la corrida cambio durante la exportacion; no se publica el indice')
    report=dict(schema_version=1,status='complete',run_id=manifest['run_id'],iteration=selection['iteration'],
        run_directory=str(Path(selection['directory']).resolve()),run_manifest_sha256=manifest_hash,
        planned_persons=manifest['counts']['planned_persons'],planned_trips=manifest['counts']['planned_trips'],
        sample_rate=1.0,window_seconds=window_seconds,replay_window=chosen,blocks=blocks,counts=stats,
        operational_counts=result['counts'],
        visual_vehicle_counts=visual_vehicle_counts,
        observation_end_probe=end_probe,
        block_segment_occurrences=block_occurrences,segments_outside_replay_window=outside_window,
        sources={**motion.sources,'events':result['events'],'network':result['network'],'plans':result['plans']},
        database='replay.sqlite',database_bytes=(folder/'replay.sqlite').stat().st_size,
        html_bytes=sum(block['html_bytes'] for block in blocks),trajectories_only=trajectories_only,
        phases_seconds=dict(metadata=metadata_done-started,events_and_motion=extraction_done-metadata_done,
                            blocks=time.perf_counter()-extraction_done,total=time.perf_counter()-started,**spool_timings),
        process_peak_working_set_bytes=peak_working_set(),
        visual_motion=dict(settings=motion.visual_settings,summary=stats.get('visual_motion',{}),scope='visual_interpolation_only'),
        native_signal_summary=native_signals.summary(),
        note='One event pass; disk-spooled complete journeys; no sampling, QSim execution or GPU FPS claim')
    annotate_observation_times(report,result['observed_event_end_seconds'])
    atomic_json(folder/'export-manifest.json',report)
    destination.write_text(index_html(report),encoding='utf-8')
    print(f'Indice generado: {destination}',flush=True)
    return report
