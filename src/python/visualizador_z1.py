"""Exporta un replay WebGL de MATSim. Ejecutar desde la raiz del proyecto.
El XML se libera incrementalmente. --sqlite-direct omite HTML paginados y
prepara SQLite para ventanas continuas. --paged conserva los historiales en SQLite
y carga una ventana temporal por pagina; el modo ordinario conserva todo en RAM.
"""
import gzip
import argparse
import xml.etree.ElementTree as ET
from pyproj import Transformer, Geod
import pydeck as pdk
import hashlib
import json
import math
from contextlib import closing
from pathlib import Path
from simz1_lane_replay import LaneEventReplay
from simz1_temporal import trip_id
from simz1_signal_replay import SignalReplay, selected_groups

PROJECT = Path(__file__).resolve().parents[1]
NETWORK_FILE = None  # Set only by explicit validated selection (or isolated unit tests).
EVENTS_FILE = None
OUTPUT_HTML = PROJECT / 'animacion_zona1.html'
SAMPLE_RATE = 1.0
GEOD = Geod(ellps='WGS84')


def elementos(path, wanted):
    with gzip.open(path, 'rb') as stream:
        context = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(context)
        for event, elem in context:
            if event == 'end' and elem.tag in wanted:
                yield elem.tag, dict(elem.attrib)
                elem.clear()
                root.clear()


def extraer_red():
    print('1. Procesando red y nodos semaforizados...')
    transformer = Transformer.from_crs('EPSG:32615', 'EPSG:4326', always_xy=True)
    nodos, links, signals = {}, {}, []
    with gzip.open(NETWORK_FILE, 'rb') as stream:
        context = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(context)
        for action, element in context:
            if action != 'end' or element.tag not in ('node', 'link'):
                continue
            attrs = element.attrib
            if element.tag == 'node':
                position = list(transformer.transform(float(attrs['x']), float(attrs['y']), errcheck=True))
                nodos[attrs['id']] = position
                metadata = {a.get('name'): a.text for a in element.findall('attributes/attribute')}
                if metadata.get('osm:highway') == 'traffic_signals':
                    signals.append({'node': attrs['id'], 'position': position})
            else:
                links[attrs['id']] = {'from': nodos[attrs['from']], 'to': nodos[attrs['to']],
                                      'from_node': attrs['from'], 'to_node': attrs['to'],
                                      'length': float(attrs['length']),
                                      'freespeed': float(attrs['freespeed']) if 'freespeed' in attrs else None}
            element.clear()
            root.clear()
    return links, signals


def color_velocidad(kmh):
    if kmh == 0:
        return [255, 255, 255]
    return [40, 210, 95] if kmh > 40 else [255, 210, 40] if kmh >= 15 else [245, 65, 65]


def seleccionado(vehicle):
    # Una decision estable por ID: un vehiculo rechazado no se vuelve a sortear.
    value = int.from_bytes(hashlib.sha256(vehicle.encode()).digest()[:8], 'big') / 2**64
    return value < SAMPLE_RATE


def extraer_trayectorias(links, incidents=None, lane_replay=None, signal_replay=None, *, motion=None, stats=None, horizon=None, segment_sink=None):
    """Read observed boundaries; estimate motion without altering event times."""
    from simz1_trajectories import extract
    if not 0 <= SAMPLE_RATE <= 1:
        raise ValueError('SAMPLE_RATE debe estar entre 0 y 1')
    report = {} if stats is None else stats
    with closing(elementos(EVENTS_FILE, {'event'})) as source:
        segments = extract((attrs for _,attrs in source), links,
            seleccionado, color_velocidad, GEOD, motion=motion, incidents=incidents,
            lane_replay=lane_replay, signal_replay=signal_replay, stats=report,horizon=horizon,segment_sink=segment_sink)
    print('Trayectorias: '+json.dumps(report,ensure_ascii=False))
    return segments


def preparar_semaforos(signals, links):
    """Todos los nodos semaforizados, con un icono por enlace entrante."""
    incoming = {}
    for link_id, link in links.items():
        bearing, _, distance = GEOD.inv(*link['from'], *link['to'])
        if distance <= 0:
            continue
        bearing %= 360
        horizontal = 45 <= bearing <= 135 or 225 <= bearing <= 315
        key = link.get('to_node', tuple(link['to']))
        incoming.setdefault(key, []).append((link_id, bearing, horizontal))
    result = []
    for signal in signals:
        lon, lat = signal['position']
        approaches = incoming.get(signal['node'], incoming.get((lon, lat), []))
        if not approaches:
            # Preserve network signals even when no approach has usable geometry.
            result.append({**signal, 'group': 'avenida', 'Link_ID': None,
                           'bearing': None, 'angle': 0, 'icon': 'unknown'})
        for link_id, bearing, horizontal in sorted(approaches):
            # Visual offsets separate the approaches without removing any signals.
            x, y, _ = GEOD.fwd(lon, lat, bearing + 180, 18)
            x, y, _ = GEOD.fwd(x, y, bearing + 90, 8)
            result.append({**signal, 'group': 'calle' if horizontal else 'avenida',
                           'Link_ID': link_id, 'bearing': bearing,
                           'angle': 90 if horizontal else 0,
                           'position': [x, y], 'icon': 'unknown'})
    return result


def preparar_senales_nativas(groups, links):
    result = []
    for group in groups:
        for signal in group['signals']:
            link = links[signal['link']]
            bearing, _, distance = GEOD.inv(*link['from'], *link['to'])
            horizontal = 45 <= bearing % 360 <= 135 or 225 <= bearing % 360 <= 315
            x,y = link['to']
            if distance > 0:
                x,y,_ = GEOD.fwd(x,y,bearing+180,18)
                x,y,_ = GEOD.fwd(x,y,bearing+90,8)
            result.append(dict(system_id=group['system_id'], group_id=group['group_id'],
                signal_id=signal['signal_id'], Link_ID=signal['link'], lane_ids=signal['lanes'],
                turning_moves=signal['turning_moves'], position=[x,y], angle=90 if horizontal else 0,
                icon='unknown'))
    return result


def atlas_semaforos():
    """Atlas PNG: estados nativos, apagado y desconocido explicitamente distinto."""
    import base64
    import io
    from PIL import Image, ImageDraw
    atlas = Image.new('RGBA', (192, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    colors = [(255, 55, 55, 255), (255, 210, 30, 255), (40, 235, 105, 255)]
    mapping = {}
    for state, name in enumerate(('red', 'yellow', 'green', 'redyellow', 'off', 'unknown')):
        x = state*32
        draw.rounded_rectangle((x+3, 2, x+29, 72), radius=7, fill='#15191f', outline='#adb5bd', width=2)
        draw.rectangle((x+14, 72, x+18, 79), fill='#adb5bd')
        for lamp in range(3):
            y = 9+21*lamp
            lit = lamp == state or name == 'redyellow' and lamp in (0,1)
            draw.ellipse((x+8, y, x+24, y+16), fill=colors[lamp] if lit else '#363e46')
        if name == 'unknown':
            draw.text((x+12,30), '?', fill='white')
        mapping[name] = dict(x=x, y=0, width=32, height=80, anchorX=16, anchorY=80, mask=False)
    output = io.BytesIO()
    atlas.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode(), mapping


def icono_colision():
    """Pictograma embebido: dos vehiculos y destello, sin recursos externos."""
    import base64
    import io
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon([(32,2),(62,58),(2,58)], fill='#ffcc33', outline='#301010', width=3)
    for x in (12,35):
        draw.rectangle((x,35,x+17,47), fill='#b51f28')
        draw.rectangle((x+3,30,x+13,36), fill='#202530')
        for wheel in (x+3,x+13):
            draw.ellipse((wheel-2,45,wheel+2,50), fill='#111111')
    draw.line([(32,20),(28,28),(35,26),(31,36)], fill='#111111', width=3)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


def icono_meta():
    """Bandera a cuadros embebida; el pie del poste es el ancla (10, 60)."""
    import base64
    import io
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line([(10, 60), (10, 5)], fill='#101820', width=6)
    draw.line([(10, 60), (10, 5)], fill='white', width=2)
    for row in range(4):
        for col in range(6):
            x, y = 12+col*8, 6+row*8
            draw.rectangle((x, y, x+7, y+7), fill='white' if (row+col)%2 == 0 else '#101820')
    draw.rectangle((11, 5, 60, 38), outline='white', width=1)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


def render_replay_html(html_content, controls, datos_trayectorias):
    """Inject a structured replay, never an error string or an unfilled template."""
    if not isinstance(datos_trayectorias, dict) or not datos_trayectorias:
        raise ValueError('El payload debe ser un objeto JSON de replay, no texto ni un error')
    layers = datos_trayectorias.get('layers')
    if not isinstance(layers, list) or not all(isinstance(layer, dict) for layer in layers):
        raise ValueError('El payload no contiene capas validas')
    for ident in ('trips', 'incidents'):
        matches = [layer for layer in layers if layer.get('id') == ident]
        if len(matches) != 1 or not isinstance(matches[0].get('data'), list):
            raise ValueError(f'El payload requiere un arreglo de datos para {ident}')
    if html_content.count('__PAYLOAD__') != 1 or html_content.count('__CONTROLS__') != 1:
        raise ValueError('La plantilla debe contener exactamente un marcador de payload y controles')
    payload = json.dumps(datos_trayectorias, separators=(',', ':'), allow_nan=False)
    # Keep arbitrary IDs safe inside the application/json script element.
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html_content = html_content.replace('__CONTROLS__', controls)
    html_content = html_content.replace('__PAYLOAD__', payload)
    return html_content


def generar_html_animado(datos_viajes, links, signals=None, incidents=None, *, selection=None,
                        output=None, lane_replay=None, replay_window=None, signal_replay=None, visual_settings=None,
                        replay_extra=None, return_config=False):
    if not isinstance(datos_viajes, list) or not all(isinstance(s, dict) and 'vehicle' in s for s in datos_viajes):
        raise ValueError('Las trayectorias deben ser un arreglo de registros, no texto de error')
    total_vehicles = len({segment['vehicle'] for segment in datos_viajes})
    if return_config:
        print('Preparando geometria y metadatos para SQLite directo; movimientos conservados en la base...')
    else:
        print(f'3. Compilando {len(datos_viajes)} tramos de {total_vehicles} vehiculos unicos...')
    roads = pdk.Layer('LineLayer', list(links.values()), id='roads',
                      get_source_position='from', get_target_position='to',
                      get_color=[110, 120, 130], get_width=1, width_min_pixels=1)
    # JS conserva los segmentos para consultar el reloj y dibuja solo posiciones activas.
    # Serialize layer definitions only: routing millions of records through
    # pydeck.to_json + json.loads needlessly duplicates the entire replay in RAM.
    trips = pdk.Layer('ScatterplotLayer', [], id='trips',
                      get_position='position', get_fill_color='color',
                      get_radius=3, radius_units=pdk.types.String('pixels'), radius_min_pixels=3,
                      radius_max_pixels=5, opacity=1, pickable=True, visible=False)
    atlas, mapping = atlas_semaforos()
    prepared_signals = (preparar_senales_nativas(signal_replay.groups,links) if signal_replay is not None
                        else preparar_semaforos(signals or [], links))
    traffic_signals = pdk.Layer('IconLayer', prepared_signals, id='signals',
        get_position='position', get_angle='angle', get_icon='icon', icon_atlas=pdk.types.String(atlas), icon_mapping=mapping,
        get_size=32, get_pixel_offset=[0, 0], size_units=pdk.types.String('pixels'), billboard=True, pickable=True)
    alerts = pdk.Layer('IconLayer', incidents or [], id='incidents',
        get_position='position', get_icon='icon', icon_atlas=pdk.types.String(icono_colision()),
        icon_mapping={'crash':dict(x=0,y=0,width=64,height=64,anchorX=32,anchorY=32,mask=False)},
        get_size=38, size_units=pdk.types.String('pixels'), billboard=True, pickable=True, visible=False)
    history = pdk.Layer('PathLayer', [], id='selected-history', get_path='path',
        get_color=[0, 139, 184], width_min_pixels=4, pickable=False)
    future = pdk.Layer('PathLayer', [], id='selected-future', get_path='path',
        get_color=[135, 225, 255], width_min_pixels=4, pickable=False)
    origin = pdk.Layer('ScatterplotLayer', [], id='selected-origin', get_position='position',
        get_fill_color=[255,255,255], get_radius=8, radius_units=pdk.types.String('pixels'),
        stroked=True, get_line_color=[20,30,40], line_width_min_pixels=2, pickable=False)
    destination = pdk.Layer('IconLayer', [], id='selected-destination', get_position='position',
        get_icon='icon', icon_atlas=pdk.types.String(icono_meta()),
        icon_mapping={'finish':dict(x=0,y=0,width=64,height=64,anchorX=10,anchorY=60,mask=False)},
        get_size=44, size_units=pdk.types.String('pixels'), billboard=True, pickable=False)
    view = pdk.ViewState(latitude=14.636, longitude=-90.513, zoom=14.5, pitch=45, bearing=0)
    # Red OSM propia sobre fondo oscuro: no exige token ni solicita teselas de pago.
    deck = pdk.Deck(layers=[roads,history,future,trips,traffic_signals,alerts,origin,destination], initial_view_state=view, map_provider=None,
                    map_style=None, tooltip={'text': 'Agente: {Agent_ID}\nVelocidad media: {Speed_kmh} km/h\nEnlace: {Link_ID}'})
    # Plantilla propia: API publica Deck, sin createDeck ni parser de expresiones.
    replay = json.loads(deck.to_json())
    next(layer for layer in replay['layers'] if layer['id']=='trips')['data'] = datos_viajes
    from simz1_visual_motion import normalize_settings
    replay['visual_motion'] = dict(settings=normalize_settings(visual_settings),
        note='Interpolacion visual experimental; no modifica eventos, metricas ni dinamica de QSim')
    # Each vehicle contributes multiple link segments; count its ID only once.
    replay['hud'] = {'reconstructed_vehicles': total_vehicles}
    if signal_replay is not None:
        replay['signal_replay'] = signal_replay.payload()
    if lane_replay is not None:
        replay['lane_replay'] = lane_replay.payload(SAMPLE_RATE)
    if selection is not None:
        manifest = selection['manifest']
        replay['trajectory_stats'] = selection.get('trajectory_stats',{})
        replay['motion_sources'] = selection.get('motion_sources',{})
        replay['trajectories_only'] = selection.get('trajectories_only',False)
        replay['hud'].update(run_id=manifest['run_id'], demand_seed=manifest['demand_seed'],
            matsim_seed=manifest['matsim_seed'], iteration=selection['iteration'],
            **manifest['counts'])
        replay['hud']['observed_departures'] = manifest['results'][str(selection['iteration'])]['counts']['observed_departures']
        replay['hud']['priority'] = manifest.get('effective_configuration_validation',
            manifest.get('configuration_validation',{})).get('unsignalized_priority')
        replay['time_horizon'] = manifest['time_horizon']
        replay['demand_window'] = manifest.get('demand_window')
        replay['replay_window'] = replay_window or manifest.get('replay_window',manifest['time_horizon'])
        replay['selection_warning'] = selection.get('selection_warning')
        if lane_replay is not None:
            from simz1_run import checked_path, parameters
            effective = checked_path(selection['directory'], manifest['effective_config'])
            use_lanes = parameters(effective).get('qsim.useLanes')
            replay['lane_replay']['use_lanes'] = None if use_lanes is None else use_lanes == 'true'
            replay['lane_replay']['configuration_sha256'] = manifest['effective_config']['sha256']
    if replay_extra:
        replay.update(replay_extra)
    if return_config:
        return replay
    template = Path(__file__).with_name('visualizador_z1.html').read_text(encoding='utf-8')
    controls = Path(__file__).with_name('visualizador_z1_controls.js').read_text(encoding='utf-8')
    html = render_replay_html(template, controls, replay)
    destination = Path(output or OUTPUT_HTML)
    destination.parent.mkdir(parents=True, exist_ok=True)
    import os
    import tempfile
    fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix='.html.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(html)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'HTML generado: {destination}')


def export_selected(selection, output=None, replay_start=None, replay_end=None, *, trajectories_only=False,
                    profile_export=False, visual_settings=None, paged=False, window_seconds=900):
    if paged:
        from simz1_paged_replay import export_paged_selected
        return export_paged_selected(selection,output,replay_start,replay_end,
            trajectories_only=trajectories_only,visual_settings=visual_settings,window_seconds=window_seconds)
    import time
    import tracemalloc
    from simz1_motion import load_selected
    from simz1_run import atomic_json
    if profile_export: tracemalloc.start()
    started = time.perf_counter()
    motion = load_selected(selection, visual_settings=visual_settings)
    metadata_done = time.perf_counter()
    global NETWORK_FILE, EVENTS_FILE
    manifest = selection['manifest']
    window = dict(manifest.get('replay_window',manifest['time_horizon']))
    window['end_seconds'] = max(window['end_seconds'],
        manifest['results'][str(selection['iteration'])].get('observed_event_end_seconds',0))
    if replay_start is not None: window['start_seconds'] = replay_start
    if replay_end is not None: window['end_seconds'] = replay_end
    if (not all(math.isfinite(v) for v in window.values()) or
            not 0 <= window['start_seconds'] < window['end_seconds']):
        raise ValueError('Ventana de replay invalida; requiere 0 <= inicio < fin finitos')
    NETWORK_FILE, EVENTS_FILE = selection['network'], selection['events']
    links_red, signals = extraer_red()
    incidents = []
    lane_replay = None if trajectories_only else LaneEventReplay(links_red)
    signal_replay = SignalReplay(selected_groups(selection,links_red))
    network_done = time.perf_counter()
    stats = {}
    trips = extraer_trayectorias(links_red, incidents, lane_replay,
        None if trajectories_only else signal_replay, motion=motion,stats=stats,horizon=manifest['time_horizon']['end_seconds'])
    events_done = time.perf_counter()
    # Keep population/event counts even when no drawable interval exists.
    selection = dict(selection,trajectory_stats=stats,motion_sources=motion.sources,
                     trajectories_only=trajectories_only)
    generar_html_animado(trips, links_red, signals, incidents, selection=selection, output=output,
                        lane_replay=lane_replay, replay_window=window, signal_replay=signal_replay,
                        visual_settings=motion.visual_settings)
    finished = time.perf_counter()
    peak = tracemalloc.get_traced_memory()[1] if profile_export else None
    if profile_export: tracemalloc.stop()
    report = dict(run_id=selection['manifest']['run_id'],iteration=selection['iteration'],
        trajectories_only=trajectories_only,counts=stats,sources=motion.sources,
        visual_motion=dict(settings=motion.visual_settings,summary=stats.get('visual_motion',{}),
                           scope='visual_interpolation_only'),
        phases_seconds=dict(metadata=metadata_done-started,network=network_done-metadata_done,
            events=events_done-network_done,html=finished-events_done,total=finished-started),
        python_traced_peak_bytes=peak,html_bytes=Path(output or OUTPUT_HTML).stat().st_size,
        note='Export wall time and Python allocations only; no WebGL/GPU FPS measurement')
    atomic_json(Path(output or OUTPUT_HTML).with_suffix('.provenance.json'), report)
    return report


def main():
    from simz1_run import select_run
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, help='Carpeta con run-manifest.json; omitir usa latest-successful')
    parser.add_argument('--iteration', type=int, help='Por defecto, ultima iteracion validada')
    parser.add_argument('--output', type=Path, help='HTML de salida; --paged usa <run-dir>/webgl/index.html por defecto')
    parser.add_argument('--trajectories-only', action='store_true', help='Omite series de carriles/senales; estados nativos se muestran desconocidos')
    parser.add_argument('--profile-export', action='store_true', help='Mide fases y pico de asignaciones Python (tracemalloc ralentiza la exportacion)')
    parser.add_argument('--paged', action='store_true', help='Exporta bloques temporales sin muestreo y SQLite para consultar el viaje seleccionado')
    parser.add_argument('--sqlite-direct', action='store_true', help='Exporta SQLite y metadatos completos sin HTML paginados; reanuda publicacion con spool-ready.json.gz')
    parser.add_argument('--sqlite-budget-gib', type=float, default=32, help='Presupuesto maximo para SQLite nuevo (GiB); comprobado antes de extraer')
    parser.add_argument('--scratch-budget-gib', type=float, default=32, help='Presupuesto de indices temporales SQLite (GiB), en --temp-dir')
    parser.add_argument('--temp-dir', type=Path, help='Directorio real para temporales de nueva exportacion SQLite')
    parser.add_argument('--window-seconds', type=float, default=900, help='Duracion de cada bloque --paged (predeterminado 900 s)')
    parser.add_argument('--motion-settings', type=Path,
                        help='JSON de aceleracion/frenado visual por perfil; no modifica entradas MATSim')
    parser.add_argument('--replay-start', type=float, help='Inicio del deslizador en segundos absolutos; no recorta eventos')
    parser.add_argument('--replay-end', type=float, help='Fin del deslizador en segundos absolutos; no altera QSim ni genera demanda')
    args = parser.parse_args()
    if (args.paged or args.sqlite_direct) and args.run_dir is None:
        parser.error('--paged/--sqlite-direct requiere --run-dir explicito para conservar la identidad de la corrida')
    if args.paged and args.sqlite_direct:
        parser.error('--paged y --sqlite-direct son alternativas excluyentes')
    try:
        settings = json.loads(args.motion_settings.read_text(encoding='utf-8')) if args.motion_settings else None
        if args.sqlite_direct:
            from simz1_sqlite_export import export_sqlite_selected
            export_sqlite_selected(select_run(args.run_dir, args.iteration), args.output,
                replay_start=args.replay_start, replay_end=args.replay_end,
                trajectories_only=args.trajectories_only, visual_settings=settings,
                window_seconds=args.window_seconds, temp_dir=args.temp_dir,
                database_budget_bytes=int(args.sqlite_budget_gib*1024**3),
                scratch_budget_bytes=int(args.scratch_budget_gib*1024**3))
            return
        export_selected(select_run(args.run_dir, args.iteration), args.output, args.replay_start, args.replay_end,
                        trajectories_only=args.trajectories_only,profile_export=args.profile_export,
                        visual_settings=settings,paged=args.paged,window_seconds=args.window_seconds)
    except (OSError, ValueError, ET.ParseError, EOFError) as exc:
        parser.exit(1, f'No se pudo generar el visor: {exc}\n')


if __name__ == '__main__':
    main()
